#! /usr/bin/env python

# pylint: disable=wrong-import-position, too-complex, too-many-locals, too-many-branches, maybe-no-member

"""
.. Note::
   The following script description was last updated on September 27, 2017.

The production script,
located at ``ConsistencyCheck/prod/compare.py`` at the time of writing,
goes through the following steps for each site.

  #. It gathers the site tree by calling
     :py:func:`ConsistencyCheck.getsitecontents.get_site_tree()`.
  #. It gathers the inventory tree by calling
     :py:func:`ConsistencyCheck.getinventorycontents.get_db_listing()`.
  #. Creates a list of datasets to not report missing files in.
     This list consists of the following.

     - Deletion requests fetched from PhEDEx by
       :py:func:`ConsistencyCheck.checkphedex.set_of_deletetion()`

  #. It creates a list of datasets to not report orphans in.
     This list consists of the following.

     - Deletion requests fetched from PhEDEx (same list as datasets to skip in missing)
     - A dataset that has any files on the site, as listed by the dynamo MySQL database
     - Any datasets that have the status flag set to ``'IGNORED'`` in the dynamo database
     - Merging datasets that are
       `protected by Unified <https://cmst2.web.cern.ch/cmst2/unified/listProtectedLFN.txt>`_

  #. Does the comparison between the two trees made.
     (Keep in mind the configuration options listed under
     :ref:`consistency-config-ref` concerning file age.)
  #. Connects to a dynamo registry to report errors.
     At the moment, if the site is ``'T2_US_MIT'``,
     this connection is made to Max's development server.
     Otherwise, the connection is to the production dynamo database.
  #. For each missing file, every possible source site as listed by the dynamo database,
     (not counting the site where missing), is entered in the transfer queue.
  #. Every orphan file and every empty directory that is not too new
     is entered in the deletion queue.

     .. Warning::
        The production script no longer cleans out site entries in the deletion or transfer queues.
        Some other tool is expected to handle that.

  #. Creates a text file that contains the missing blocks and groups.
  #. ``.txt`` file lists and details of orphan and missing files are moved to the web space
     and the stats database is updated.

:author: Daniel Abercrombie <dabercro@mit.edu>
"""

import logging
import sys
import os
import sqlite3
import shutil
import time
import datetime

from collections import defaultdict

from ConsistencyCheck import config

# Stick this here before dynamo sets the logging config
if __name__ == '__main__':
    if len(sys.argv) < 2 or '-h' in sys.argv or '--help' in sys.argv:
        print 'Usage: ./compare.py sitename [sitename ...] [debug/watch]'
        exit(0)

    # Set the config file to read locally
    config.CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                      'consistency_config.json')

    SITES = sys.argv[1:-1]

    # Set the logging level based on the verbosity option

    LOG_FORMAT = '%(asctime)s:%(levelname)s:%(name)s: %(message)s'

    if 'debug' in sys.argv:
        logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)
    elif 'watch' in sys.argv:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    # If no valid verbosity level, assume the last arg was a sitename
    else:
        SITES.append(sys.argv[-1])


from ConsistencyCheck import getsitecontents
from ConsistencyCheck import getinventorycontents
from ConsistencyCheck import datatypes
from ConsistencyCheck import checkphedex

from CMSToolBox.webtools import get_json
from common.interface.mysql import MySQL

LOG = logging.getLogger(__name__)

def main(site):
    """
    Gets the listing from the dynamo database, and remote XRootD listings of a given site.
    The differences are compared to deletion queues and other things.

    .. Note::
       If you add things, list them in the module docstring.

    The differences that should be acted on are copied to the summary webpage
    and entered into the dynamoregister database.

    :param str site: The site to run the check over
    :returns: missing files, size, orphan files, size
    :rtype: list, long, list, long
    """

    start = time.time()

    prev_missing = '%s_compare_missing.txt' % site
    prev_set = set()
    if os.path.exists(prev_missing):
        with open(prev_missing, 'r') as prev_file:
            for line in prev_file:
                prev_set.add(line.strip())

        if int(config.config_dict().get('SaveCache')):
            prev_new_name = '%s.%s' % (prev_missing,
                                       datetime.datetime.fromtimestamp(
                                           os.stat(prev_missing).st_mtime).strftime('%y%m%d')
                                      )
        else:
            prev_new_name = prev_missing

        shutil.move(prev_missing,
                    os.path.join(config.config_dict()['CacheLocation'],
                                 prev_new_name)
                   )

    # All of the files and summary will be dumped here
    webdir = config.config_dict()['WebDir']

    # Open a connection temporarily to make sure we only list good sites
    status_check = MySQL(config_file='/etc/my.cnf', db='dynamo', config_group='mysql-dynamo')
    status = status_check.query('SELECT status FROM sites WHERE name = %s', site)[0]

    if status != 'ready':
        LOG.error('Site %s status is %s', site, status)

        # Note the attempt to do listing
        conn = sqlite3.connect(os.path.join(webdir, 'stats.db'))
        curs = conn.cursor()
        curs.execute(
            """
            REPLACE INTO stats VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, DATETIME(DATETIME(), "-4 hours"), ?, ?)
            """,
            (site, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        conn.commit()
        conn.close()

        exit(0)

    # Close the connection while we are getting the trees together
    status_check.close()

    inv_tree = getinventorycontents.get_db_listing(site)
    site_tree = getsitecontents.get_site_tree(site)

    # Get whether or not the site is debugged
    conn = sqlite3.connect(os.path.join(webdir, 'stats.db'))
    curs = conn.cursor()
    curs.execute('SELECT isgood FROM sites WHERE site = ?', (site, ))
    is_debugged = curs.fetchone()[0]
    conn.close()

    # Create the function to check orphans and missing

    # First, datasets in the deletions queue can be missing
    acceptable_missing = checkphedex.set_of_deletions(site)

    # Orphan files cannot belong to any dataset that should be at the site
    inv_sql = MySQL(config_file='/etc/my.cnf', db='dynamo', config_group='mysql-dynamo')
    acceptable_orphans = set(
        inv_sql.query(
            """
            SELECT datasets.name FROM sites
            INNER JOIN dataset_replicas ON dataset_replicas.site_id=sites.id
            INNER JOIN datasets ON dataset_replicas.dataset_id=datasets.id
            WHERE sites.name=%s
            """,
            site)
        )

    # Orphan files may be a result of deletion requests
    acceptable_orphans.update(acceptable_missing)

    # Ignored datasets will not give a full listing, so they can't be accused of having orphans
    acceptable_orphans.update(
        inv_sql.query('SELECT name FROM datasets WHERE status=%s', 'IGNORED')
        )

    # Do not delete anything that is protected by Unified
    protected_unmerged = get_json('cmst2.web.cern.ch', '/cmst2/unified/listProtectedLFN.txt')
    acceptable_orphans.update(['/%s/%s-%s/%s' % (split_name[4], split_name[3],
                                                 split_name[6], split_name[5]) \
                                   for split_name in \
                                   [name.split('/') for name in protected_unmerged['protected']]
                              ])

    LOG.debug('Acceptable orphans: \n%s\n', '\n'.join(acceptable_orphans))

    def double_check(file_name, acceptable):
        """
        Checks the file name against a list of datasets to not list files from.

        :param str file_name: LFN of the file
        :param set acceptable: Datasets to not list files from
                               (Acceptable orphans or missing)
        :returns: Whether the file belongs to a dataset in the list or not
        :rtype: bool
        """
        LOG.debug('Checking file_name: %s', file_name)
        split_name = file_name.split('/')
        try:
            return '/%s/%s-%s/%s' % (split_name[4], split_name[3],
                                     split_name[6], split_name[5]) in acceptable
        except IndexError:
            LOG.warning('Strange file name: %s', file_name)
            return True

    check_orphans = lambda x: double_check(x, acceptable_orphans)
    check_missing = lambda x: double_check(x, acceptable_missing)

    # Do the comparison
    missing, m_size, orphan, o_size = datatypes.compare(
        inv_tree, site_tree, '%s_compare' % site,
        orphan_check=check_orphans, missing_check=check_missing)

    LOG.debug('Missing size: %i, Orphan size: %i', m_size, o_size)

    # Whether or not to skip entering missing files into the registry
    skip_enter = len(missing) > int(config.config_dict()['MaxMissing'])
    if skip_enter:
        LOG.warning('Too many missing files: %i, you should investigate.', len(missing))
    else:
        skip_enter = not is_debugged

    # Enter things for site in registry
    if os.environ['USER'] == 'dynamo':
        reg_sql = MySQL(config_file='/etc/my.cnf', db='dynamoregister',
                        config_group='mysql-dynamo')
    else:
        reg_sql = MySQL(config_file='%s/my.cnf' % os.environ['HOME'], db='dynamoregister',
                        config_group='mysql-register-test')

    no_source_files = []

    def add_transfers(line, sites):
        """
        Add the file into the transfer queue for multiple sites.

        :param str line: The file LFN to transfer
        :param list sites: Sites to try to transfer from
        :returns: Whether or not the entry was a success
        :rtype: bool
        """

        # Don't add transfers if too many missing files
        if not skip_enter and (line in prev_set or not prev_set):
            for location in sites:
                reg_sql.query(
                    """
                    INSERT IGNORE INTO `transfer_queue`
                    (`file`, `site_from`, `site_to`, `status`, `reqid`)
                    VALUES (%s, %s, %s, 'new', 0)
                    """,
                    line, location, site)

                LOG.info('Copying %s from %s', line, location)

        return bool(sites)


    # Setup a query for sites, with added condition at the end
    site_query = """
                 SELECT sites.name FROM sites
                 INNER JOIN block_replicas ON sites.id = block_replicas.site_id
                 INNER JOIN files ON block_replicas.block_id = files.block_id
                 WHERE files.name = %s AND sites.name != %s
                 AND sites.status = 'ready'
                 AND block_replicas.is_complete = 1
                 {0}
                 """

    for line in missing:

        # Get sites that are not tape
        sites = inv_sql.query(
            site_query.format('AND sites.storage_type != "mss"'),
            line, site)

        if not add_transfers(line, sites):
            # Track files without disk source
            no_source_files.append(line)

            # Get sites that are tape
            sites = inv_sql.query(
                site_query.format('AND sites.storage_type = "mss"'),
                line, site)

            add_transfers(line, sites)


    with open('%s_missing_nosite.txt' % site, 'w') as nosite:
        for line in no_source_files:
            nosite.write(line + '\n')


    # Only get the empty nodes that are not in the inventory tree
    if is_debugged:
        for line in orphan + \
                [empty_node for empty_node in site_tree.empty_nodes_list() \
                     if not inv_tree.get_node('/'.join(empty_node.split('/')[2:]),
                                              make_new=False)]:
            reg_sql.query(
                """
                INSERT IGNORE INTO `deletion_queue`
                (`file`, `site`, `status`) VALUES
                (%s, %s, 'new')
                """,
                line, site)

            LOG.info('Deleting %s', line)


    reg_sql.close()

    # We want to track which blocks missing files are coming from
    track_missing_blocks = defaultdict(
        lambda: {'errors': 0,
                 'blocks': defaultdict(lambda: {'group': '',
                                                'errors': 0}
                                      )
                })

    blocks_query = """
                   SELECT blocks.name, IFNULL(groups.name, 'Unsubscribed') FROM blocks
                   INNER JOIN files ON files.block_id = blocks.id
                   INNER JOIN block_replicas ON block_replicas.block_id = files.block_id
                   INNER JOIN sites ON block_replicas.site_id = sites.id
                   LEFT JOIN groups ON block_replicas.group_id = groups.id
                   WHERE files.name = %s AND sites.name = %s
                   """

    with open('%s_compare_missing.txt' % site, 'r') as input_file:
        for line in input_file:
            split_name = line.split('/')
            dataset = '/%s/%s-%s/%s' % (split_name[4], split_name[3], split_name[6], split_name[5])

            output = inv_sql.query(blocks_query, line.strip(), site)

            if not output:
                LOG.warning('The following SQL statement failed: %s',
                            blocks_query % (line.strip(), site))
                LOG.warning('Most likely cause is dynamo update between the listing and now')
                from_phedex = get_json('cmsweb.cern.ch', '/phedex/datasvc/json/prod/filereplicas',
                                       params={'node': site, 'LFN': line.strip()}, use_cert=True)

                try:
                    output = [(from_phedex['phedex']['block'][0]['name'].split('#')[1],
                               from_phedex['phedex']['block'][0]['replica'][0]['group'])]
                except IndexError:
                    LOG.error('File replica not in PhEDEx either!')
                    LOG.error('Skipping block level report for this file.')
                    continue

            block, group = output[0]

            track_missing_blocks[dataset]['errors'] += 1
            track_missing_blocks[dataset]['blocks'][block]['errors'] += 1
            track_missing_blocks[dataset]['blocks'][block]['group'] = group

    inv_sql.close()

    # Output file with the missing datasets
    with open('%s_missing_datasets.txt' % site, 'w') as output_file:
        for dataset, vals in \
                sorted(track_missing_blocks.iteritems(),
                       key=lambda x: x[1]['errors'],
                       reverse=True):

            for block_name, block in sorted(vals['blocks'].iteritems()):
                output_file.write('%10i    %-17s  %s#%s\n' % \
                                      (block['errors'], block['group'],
                                       dataset, block_name))

    # If there were permissions or connection issues, no files would be listed
    # Otherwise, copy the output files to the web directory
    shutil.copy('%s_missing_datasets.txt' % site, webdir)
    shutil.copy('%s_missing_nosite.txt' % site, webdir)
    shutil.copy('%s_compare_missing.txt' % site, webdir)
    shutil.copy('%s_compare_orphan.txt' % site, webdir)

    # Update the runtime stats on the stats page
    conn = sqlite3.connect(os.path.join(webdir, 'stats.db'))
    curs = conn.cursor()

    curs.execute('INSERT INTO stats_history SELECT * FROM stats WHERE site=?', (site, ))
    curs.execute(
        """
        REPLACE INTO stats VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, DATETIME(DATETIME(), "-4 hours"), ?, ?)
        """,
        (site, time.time() - start, site_tree.get_num_files(),
         site_tree.count_nodes(), len(site_tree.empty_nodes_list()),
         config.config_dict().get('NumThreads', config.config_dict().get('MinThreads', 0)),
         len(missing), m_size, len(orphan), o_size, len(no_source_files),
         site_tree.get_num_files(unlisted=True)))

    conn.commit()
    conn.close()


if __name__ == '__main__':

    LOG.info('About to run over %s', SITES)

    for site_to_check in SITES:
        main(site_to_check)
