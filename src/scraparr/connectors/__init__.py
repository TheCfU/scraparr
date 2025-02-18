"""
Connectors module to dynamically get the Services.
And update their Metrics
"""

import hashlib
import json
import logging
import concurrent.futures
from scraparr.util import get

indexers = ["sonarr", "radarr"]

class Connectors:
    """Class to initialize Variables that are used to Identify the Connectors
    and log the last Scrape"""
    def __init__(self):
        self.connectors = {}
        self.last_scrape = {}

    def add_connector(self, service, configs):
        """Function to add a Connector on successful load into the List of Connectors"""
        importer = self.load_connector(service)

        if importer:
            self.connectors[service] = []
            for config in configs:
                connector_entry = {
                    "function": importer,
                    "config": config
                }
                self.connectors[service].append(connector_entry)
                self.last_scrape[service] = [None] * len(configs)  # track last scrape per config
        else:
            logging.error("Couldn't import Connector")

    @staticmethod
    def load_connector(service):
        """Function to Load the Connector from the Connectors Folder"""
        try:
            return __import__(f"scraparr.connectors.{service}", fromlist=[service])
        except ImportError:
            logging.error("No connector found for %s", service)
            return None

    @staticmethod
    def get_hash(data):
        """Function to get the Hash of the Data"""
        return hashlib.md5(json.dumps(data, sort_keys=True).encode('utf-8')).hexdigest()

    def scrape_service(self, service, config_index):
        """Function to Scrape the Service and Update the Metrics"""
        config = self.connectors[service][config_index]["config"]
        scrape_data = {"data": self.connectors[service][config_index]["function"].scrape(config),
                       "system": self.get_system_data(service, config)}
        if scrape_data["data"] is not None and scrape_data["system"] is not None:
            new_hash = self.get_hash(scrape_data)
            if new_hash != self.last_scrape[service][config_index]:
                self.last_scrape[service][config_index] = new_hash
                func = self.connectors[service][config_index]["function"]
                func.update_metrics(
                    scrape_data,
                    config.get('detailed', False),
                    config.get('alias', service)
                )
                logging.info("%s metrics updated for config %d", service, config_index)
            else:
                logging.info("No changes detected in %s for config %d", service, config_index)
        else:
            logging.warning("%s scrape failed for config %d", service, config_index)

    @staticmethod
    def get_system_data(service, config):
        """Function to get the System Data"""
        def root_folder():
            data = get(f"{url}/api/{api_version}/rootfolder", api_key)
            if data:
                diskspace_data = get(f"{url}/api/{api_version}/diskspace", api_key)
                if diskspace_data:
                    report = []
                    for disk in diskspace_data:
                        if any(disk["path"] == d["path"] for d in data):
                            report.append(disk)
                    return report
            return None

        def queue():
            return get(f"{url}/api/{api_version}/queue/status", api_key)

        def status():
            return get(f"{url}/api/{api_version}/system/status", api_key)

        url = config.get('url')
        api_key = config.get('api_key')
        api_version = config.get('api_version', 'v1')

        if service in indexers:
            return {'root_folder': root_folder(), 'queue': queue(), 'status': status()}
        return {'status': status()}

    def scrape(self):
        """Function to Scrape all the Services"""
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(self.scrape_service, service, config_index): (service, config_index)
                for service, configs in self.connectors.items()
                for config_index in range(len(configs))
            }
            for future in concurrent.futures.as_completed(futures):
                service, config_index = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logging.error("Scrape failed for %s (config %d): %s", service, config_index, e)
                    raise e
