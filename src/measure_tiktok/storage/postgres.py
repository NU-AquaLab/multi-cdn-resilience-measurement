"""PostgreSQL connections and queries for measurement data."""

import logging
import os
from typing import Optional

import psycopg2

logger = logging.getLogger(__name__)


class PostgresDB:
    """Read and write the measurement database using psycopg2."""

    def __init__(self):
        self.db_name = os.getenv("DB_NAME")
        self.user = os.getenv("DB_USER")
        self.password = os.getenv("DB_PASSWORD")
        self.host = os.getenv("DB_HOST")
        self.port = os.getenv("DB_PORT", "5432")
        self.conn = None
        self.cursor = None

        try:
            self.conn = psycopg2.connect(
                dbname=self.db_name,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
            )
            self.cursor = self.conn.cursor()
            logger.info("Connected to the database successfully.")
        except Exception:
            logger.warning("Could not connect to the database")
            raise

    def disconnect(self):
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

    def insert(self, query: str, data: tuple):
        try:
            self.cursor.execute(query, data)
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Error inserting data: {e}")
            self.conn.rollback()
            raise

    def read_db_table(self, select_query: str, where_statement: Optional):
        try:
            self.cursor.execute(select_query, (where_statement,))
            results = self.cursor.fetchall()
            return results
        except Exception as e:
            logger.warning(f"Error reading data: {e}")
            self.conn.rollback()
            raise

    def get_videos_in_db_by_platform(self, platform: str, table_name: str):
        query = f"""
            SELECT  
                DISTINCT(webpage_url)
            FROM 
                {table_name}
            WHERE 
                webpage_url_domain = '{platform}'
        """
        video_urls = self.read_db_table(query, None)
        video_urls = list([video_url[0] for video_url in video_urls])
        return video_urls

    def get_countries_in_table(self, table_name: str):
        query = f"""
            SELECT  
                DISTINCT(country_code)
            FROM 
                {table_name}
        """
        countries = self.read_db_table(query, None)
        countries = list([country[0] for country in countries])
        return countries

    def read_cache_status_data(self, platform: str, table_name: str):
        query = f"""
            SELECT  
                x_cache, x_cache_remote, x_parent_response, x_origin_response, timing, network_cdn_url
            FROM 
                {table_name}

        """
        res = self.read_db_table(query, None)
        return res

    def read_popularity_cache_status_data(
        self, platform: str, table_name: str, country_codes
    ):
        query = f"""
            SELECT  
                video_id, view_count, like_count, comment_count, x_cache, x_cache_remote, x_parent_response, x_origin_response, timing, network_cdn_url, crawler_timestamp, country_code
            FROM 
                {table_name}
            Where country_code in ({country_codes})

        """
        res = self.read_db_table(query, None)
        return res

    def read_vod_metadata(self, platform: str, table_name: str):
        query = f"""
            SELECT  
                video_id, view_count, like_count, comment_count, x_cache, x_cache_remote, network_cdn_url, crawler_timestamp, city, region, country_code
            FROM 
                {table_name}
        """
        res = self.read_db_table(query, None)
        return res

    def read_popularity_cache_status_data_unique_videos(
        self, platform: str, table_name: str
    ):
        query = f"""
            WITH latest_videos AS (
                SELECT *, 
                    ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY crawler_timestamp ASC) AS row_num
                FROM {table_name}
            )
            SELECT  
                video_id, view_count, like_count, comment_count, x_cache, x_cache_remote, 
                x_parent_response, x_origin_response, timing, network_cdn_url, crawler_timestamp
            FROM latest_videos
            WHERE row_num = 1;
        """
        res = self.read_db_table(query, None)
        return res

    def video_ids_with_view_count_change(self, table_name: str):
        query = f"""
            WITH ranked_videos AS (
                SELECT
                    video_id,
                    view_count,
                    crawler_timestamp,
                    x_cache,
                    LAG(view_count) OVER (PARTITION BY video_id ORDER BY crawler_timestamp) AS prev_view_count
                FROM {table_name}
                WHERE view_count > 0 and x_cache is not NULL
            )
            SELECT video_id, view_count, crawler_timestamp, x_cache
            FROM ranked_videos
            WHERE prev_view_count IS NOT NULL
                AND view_count > prev_view_count
                AND video_id IN (
                    SELECT video_id FROM ranked_videos WHERE prev_view_count IS NOT NULL AND view_count > prev_view_count
                    GROUP BY video_id HAVING COUNT(*) > 1
                );
        """
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return results

    def get_stats_from_vpns(self, table_name: str):
        query = f"""
            SELECT count(video_id), city
                from {table_name}
            group by city;
        """
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return results

    def get_video_info_by_city(self, table_name: str, city: str):
        query = f"""
            SELECT video_id, view_count, like_count, comment_count, x_cache, x_cache_remote,
                x_parent_response, x_origin_response, timing, network_cdn_url, crawler_timestamp
            FROM {table_name}
            WHERE city = %s
        """
        self.cursor.execute(query, (city,))
        results = self.cursor.fetchall()
        return results

    def get_live_streaming_data(self, table_name):
        query = f"""
            SELECT  
                country_code, cdn_host_name, cdn_servers
            FROM 
                {table_name}
        """
        res = self.read_db_table(query, None)
        return res

    def get_live_streaming_fallback_data(self, table_name, country_codes: str):
        query = f"""
            SELECT start_time, fallback_delay, viewer_count, blocked_ip, resolved_ip, blocked_hostname, resolved_hostname, timezone, city, region, country_code
            FROM {table_name}
            Where country_code in ({country_codes})
        """
        res = self.read_db_table(query, None)
        return res

    def get_all_live_streaming_fallback_data(self, table_name, country_codes):
        query = f"""
            SELECT room_id, start_time, fallback_delay, viewer_count, blocked_ip, resolved_ip, timezone, city, region, country_code
            FROM {table_name}
            Where country_code in ({country_codes})
        """
        res = self.read_db_table(query, None)
        return res

    def get_vod_fallback_data(self, table_name, where_clause):
        query = f"""
            SELECT video_link, crawler_timestamp, resource_id, fallback_logs, city, region, country_code, timezone
            FROM {table_name}
        """
        if where_clause:
            query += f" WHERE {where_clause}"
        res = self.read_db_table(query, None)
        return res

    def get_vod_fallback_iterative_data(self, table_name, where_clause):
        query = f"""
            SELECT video_link, resource_id, start_time, fallback_logs, whole_fallback_delay, index
            FROM {table_name}
        """
        if where_clause:
            query += f" WHERE {where_clause}"
        res = self.read_db_table(query, None)
        return res

    def get_vod_mobile_data(self, table_name, country_codes):
        query = f"""
            SELECT edge_src_ip, x_cache, extra_info, group_id, play_type, country_code
            FROM {table_name}
            Where country_code in ({country_codes})
        """
        res = self.read_db_table(query, None)
        return res


class InfraDB:
    """Access an optional infrastructure geolocation database."""

    def __init__(self):
        self.db_name = "infra"
        self.user = os.getenv("DB_USER")
        self.password = os.getenv("DB_PASSWORD")
        self.host = os.getenv("INFRA_DB_HOST", os.getenv("DB_HOST"))
        self.port = os.getenv("DB_PORT", "5432")
        self.conn = None
        self.cursor = None

        try:
            self.conn = psycopg2.connect(
                dbname=self.db_name,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
            )
            self.cursor = self.conn.cursor()
            logger.info("Connected to the database successfully.")
        except Exception:
            logger.warning("Could not connect to the database")
            raise

    def disconnect(self):
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

    def geolocate_ip(self, ip: str):
        query = """
            SELECT 
                asn, asn_name, city, region, country, lat, lon
            FROM 
                addrinfo
            WHERE 
                addr = %s
        """
        self.cursor.execute(query, (ip,))
        result = self.cursor.fetchone()
        return result if result else None

    def insert(self, query: str, data: tuple):
        try:
            self.cursor.execute(query, data)
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Error inserting data: {e}")
            self.conn.rollback()
            raise
