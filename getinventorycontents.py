# pylint: disable=import-error, protected-access

"""
This module gets the information from the inventory about a site's contents

:author: Daniel Abercrombie <dabercro@mit.edu>
"""

import time
import logging

from common.inventory import InventoryManager
from common.dataformat import File
from common.dataformat import Dataset
from common.interface.mysql import MySQL

from . import datatypes
from . import config
from . import cache_tree

LOG = logging.getLogger(__name__)

class InvLoader(object):
    """
    Creates an InventoryManager object, if needed,
    and stores it globally for the module.
    It also holds a list of datasets in the deletion queue.
    """
    def __init__(self):
        """Initializer for the object"""
        self.inv = None
        self.deletions = None

    def get_inventory(self):
        """
        Make an inventory, if needed, and return it.

        :returns: Any InventoryManager in the vicinity.
        :rtype: common.inventory.InventoryManager
        """
        if self.inv is None:
            self.inv = InventoryManager()

        return self.inv


INV = InvLoader()


@cache_tree('InventoryAge', 'inventorylisting')
def get_site_inventory(site):
    """ Loads the contents of a site, based on the dynamo inventory

    :param str site: The name of the site to load
    :returns: The file replicas that are supposed to be at a site
    :rtype: ConsistencyCheck.datatypes.DirectoryInfo
    """

    tree = datatypes.DirectoryInfo('/store')

    inventory = INV.get_inventory()
    replicas = inventory.sites[site].dataset_replicas

    # Only look in directories in the configuration file
    dirs_to_look = config.config_dict()['DirectoryList']

    for replica in replicas:
        add_list = []
        inventory.store.load_files(replica.dataset)
        blocks_at_site = [brep.block for brep in replica.block_replicas]
        for file_at_site in replica.dataset.files:
            if file_at_site.block not in blocks_at_site:
                continue
            # Make sure we don't waste time/space on directories we don't compare
            if File.directories[file_at_site.directory_id].split('/')[2] in dirs_to_look:

                last_created = replica.last_block_created if replica.is_complete \
                              else int(time.time())
                add_list.append((file_at_site.fullpath(), file_at_site.size,
                                 last_created, file_at_site.block.real_name()))

        tree.add_file_list(add_list)

    return tree


def set_of_ignored():
    """
    Get the full list of IGNORED datasets from the inventory
    """
    inv = INV.get_inventory()
    ignored = set()

    for dataset, details in inv.datasets.iteritems():
        if details.status == Dataset.STAT_IGNORED:
            ignored.add(dataset)

    return ignored


@cache_tree('InventoryAge', 'mysqllisting')
def get_db_listing(site):
    """
    Get the list of files from dynamo database directly from MySQL.

    :param str site: The name of the site to load
    :returns: The file replicas that are supposed to be at a site
    :rtype: ConsistencyCheck.datatypes.DirectoryInfo
    """

    inv_sql = MySQL(config_file='/etc/my.cnf', db='dynamo', config_group='mysql-dynamo')

    # Get list of files
    curs = inv_sql._connection.cursor()

    LOG.info('About to make MySQL query for files at %s', site)

    tree = datatypes.DirectoryInfo('/store')

    def add_to_tree(curs):
        """
        Add cursor contents to the dynamo listing tree

        :param MySQLdb.cursor curs: The cursor which just completed a query to fetch
        """
        dirs_to_look = iter(sorted(config.config_dict()['DirectoryList']))

        files_to_add = []
        look_dir = ''
        row = curs.fetchone()

        while row:
            name, size = row[0:2]
            timestamp = time.mktime(row[2].timetuple()) if len(row) == 3 else 0

            current_directory = name.split('/')[2]
            try:
                while look_dir < current_directory:
                    look_dir = next(dirs_to_look)
            except StopIteration:
                break

            if current_directory == look_dir:
                LOG.debug('Adding file: %s, %i', name, size)

                files_to_add.append((name, size, timestamp))

            row = curs.fetchone()

        tree.add_file_list(files_to_add)

    curs.execute(
        """
        SELECT files.name, files.size
        FROM block_replicas
        INNER JOIN sites ON block_replicas.site_id = sites.id
        INNER JOIN files ON block_replicas.block_id = files.block_id
        WHERE block_replicas.is_complete = 1 AND sites.name = %s
        ORDER BY files.name ASC
        """,
        (site,))

    add_to_tree(curs)

    curs.execute(
        """
        SELECT files.name, files.size, NOW()
        FROM block_replicas
        INNER JOIN sites ON block_replicas.site_id = sites.id
        INNER JOIN files ON block_replicas.block_id = files.block_id
        WHERE block_replicas.is_complete = 0 AND sites.name = %s
        ORDER BY files.name ASC
        """,
        (site,))

    add_to_tree(curs)

    LOG.info('MySQL query returned')

    return tree
