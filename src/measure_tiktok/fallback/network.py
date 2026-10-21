"""Resolve delivery addresses and manage experiment firewall rules."""

import ipaddress
import logging
import os
import socket
import subprocess
from collections import Counter

import pyshark

from measure_tiktok.utils import common as util
from measure_tiktok.utils.common import resolve_hostname_ips

logger = logging.getLogger(__name__)


class NetworkController:
    """Apply and remove IP blocking rules for an experiment."""

    def __init__(self, selenium):
        self.my_ip = self.get_my_ip()
        self.selenium = selenium

    def get_my_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip

    def resolve_ip_range(self, hostname):
        subnets = set()
        try:
            ip_addresses = resolve_hostname_ips(hostname)
            for ip_str in ip_addresses:
                try:
                    subnet = ipaddress.ip_network(f"{ip_str}/24", strict=False)
                    subnets.add(str(subnet))
                except ValueError:
                    logger.warning(f"Skipping invalid IP: {ip_str}")

            ip_ranges = sorted(subnets)

            logger.info(f"Found host IP address ranges of hostname {hostname}:")
            logger.info(ip_ranges)

            return ip_ranges
        except Exception as e:
            logger.warning(f"Error resolving IPs for {hostname}: {e}")

            return []

    def get_curr_ip_range(self, target_ip_ranges, packet_count=200):
        """
        Capture {packet_count} TCP packets coming to my IP using Wireshark.
        From the captured packets, check for source IPs within target IP ranges, resolved from the
        hostname of stream URL. Then apply majority vote to heuristically
        identify the source IP range of current stream.
        """

        logger.info(
            "Starting packet capture to find source IP range for current stream..."
        )
        cap = pyshark.LiveCapture(
            interface=os.getenv(
                "CAPTURE_INTERFACE", "en0" if os.sys.platform == "darwin" else "eth0"
            ),
            display_filter="tcp.port == 443",
        )
        filtered_src_ips = []

        try:
            subnet_objects = [
                ipaddress.ip_network(prefix, strict=False)
                for prefix in target_ip_ranges
            ]
        except Exception as e:
            logger.warning(
                f"Couldn't get current IP range. Error parsing target IP ranges: {e}"
            )
            return None

        try:
            for packet in cap.sniff_continuously(packet_count=packet_count):
                try:
                    if hasattr(packet, "ip") and packet.ip.dst == self.my_ip:
                        src_ip = packet.ip.src
                        ip_obj = ipaddress.ip_address(src_ip)
                        if any(ip_obj in subnet for subnet in subnet_objects):
                            filtered_src_ips.append(src_ip)
                except AttributeError:
                    continue

        except Exception as e:
            logger.warning(
                f"Couldn't get current IP range. Error during packet capture: {e}"
            )
            return None

        if not filtered_src_ips:
            logger.warning(
                "Couldn't get current IP range. No matching source IPs within target IP ranges were captured."
            )
            return None

        counter = Counter(filtered_src_ips)
        most_common_src, count = counter.most_common(1)[0]

        subnet = str(ipaddress.ip_network(f"{most_common_src}/24", strict=False))
        logger.info(f"Corresponding /24 subnet: {subnet}")

        return subnet

    def create_block_rule(self, need_to_block, os_type):
        if os_type == "linux":
            rule = "".join(
                f"iptables -A OUTPUT -d {ip} -j DROP\n" for ip in need_to_block
            )
        else:
            rule = "".join(f"block drop out quick to {ip}\n" for ip in need_to_block)
        return rule

    def block_ips_by_rule(self, rule, os_type):
        """
        Linux version: block IPs using iptables rules from a single string (one per line).
        Mimics macOS-style block rule application.
        """
        try:
            if os_type == "linux":
                for line in rule.strip().splitlines():
                    subprocess.run(
                        ["sudo"] + line.strip().split(),
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            elif os_type == "mac":
                subprocess.run(
                    ["sudo", "tee", "-a", "/etc/pf.conf"],
                    input=rule,
                    text=True,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                os.system("sudo pfctl -f /etc/pf.conf")

            block_time = util.get_uuid_timestamp()
            logger.info(f"Blocked IP rule(s):\n{rule}\nat {block_time}")
            return block_time

        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to apply iptables rule: {e}")
            return None

    def cleanup_ipconfig(self, blocked_ips, os_type):
        logger.info("Cleaning up ip firewall config rules...")
        if os_type == "linux":
            for ip in blocked_ips:
                try:
                    subprocess.run(
                        ["sudo", "iptables", "-D", "OUTPUT", "-d", ip, "-j", "DROP"],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    logger.info(f"Unblocked IP: {ip}")
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to remove iptables rule for {ip}: {e}")
        elif os_type == "mac":
            try:
                with open("/etc/pf.conf") as f:
                    lines = f.readlines()

                rules_to_remove = {
                    f"block drop out quick to {ip}\n" for ip in blocked_ips
                }
                updated_lines = [line for line in lines if line not in rules_to_remove]
                cleaned_content = "".join(updated_lines)

                subprocess.run(
                    ["sudo", "tee", "/etc/pf.conf"],
                    input=cleaned_content,
                    text=True,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                os.system("sudo pfctl -f /etc/pf.conf")
                logger.info("Removed IP blocking rule and reloaded pfctl.")
            except Exception as e:
                logger.warning(f"PF cleanup failed: {e}")

    def is_resolved(self, curr_stream_id, blocked_ip_ranges, room_id):
        """
        Get current stream URL, resolve IP range
        """

        try:
            hostname, stream_id = self.selenium.get_curr_stream_request(room_id)

            if stream_id != curr_stream_id:
                logger.warning("Failed to find current stream URL from log")
                return False, None, None

            new_ip_ranges = resolve_hostname_ips(hostname)

            if not new_ip_ranges:
                logger.warning("Failed to detect IP range for current stream")

            blocked_set = {ipr.strip() for ipr in blocked_ip_ranges}
            new_set = {ipr.strip() for ipr in new_ip_ranges}

            new_ips = list(new_set - blocked_set)
            if new_ips:
                logger.info(f"Detected new IPs serving current stream: {new_ips}")
                return True, hostname, new_ips
            else:
                logger.warning(
                    f"No new IPs detected; stream still on blocked IPs: {blocked_ip_ranges}"
                )
                return False, hostname, None

        except KeyboardInterrupt:
            raise

        except Exception as e:
            logger.warning(f"Error while checking fallback resolution: {e}")
