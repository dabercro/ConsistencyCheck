"""
Tool to get the files located at a site.

.. Warning::

   Must be used on a machine with XRootD python module installed.

:author: Daniel Abercrombie <dabercro@mit.edu>
"""


import re
import logging
import random
import itertools

import XRootD.client
import timeout_decorator

from . import config
from . import datatypes
from . import cache_tree

LOG = logging.getLogger(__name__)

class XRootDLister(object):
    """
    A class that holds two XRootD connections.
    If the primary connection fails to list a directory,
    then a fallback connection is used.
    This keeps the load of listing from hitting more than half
    of a site's doors at a time.
    """

    def __init__(self, primary_door, backup_door, site, thread_num=None, do_both=False):
        """
        Set up the class with two doors.

        :param str primary_door: The URL of the door that will get the most load
        :param str backup_door: The URL of the door that will be used when
                                the primary door fails
        :param str site: The site that this connection is to.
        :param int thread_num: This optional parameter is only used to
                               Create a separate logger for this object
        :param bool do_both: If true, the primary and backup doors will both
                             be used for every listing
        """

        self.primary_conn = XRootD.client.FileSystem(primary_door)
        self.backup_conn = XRootD.client.FileSystem(backup_door)
        self.do_both = do_both
        self.tries = config.config_dict().get('Retries', 0) + 1
        self.site = site

        # This regex is used to parse the error code and propose a retry
        self.error_re = re.compile(r'\[(\!|\d+|FATAL)\]')

        if thread_num is None:
            self.log = logging.getLogger(__name__)
        else:
            self.log = logging.getLogger('%s--thread%i' % (__name__, thread_num))

        self.log.info('Connections created at %s (primary) and %s (backup)',
                      primary_door, backup_door)

    @timeout_decorator.timeout(config.config_dict()['Timeout'], use_signals=True)
    def ls_directory(self, door, path):
        """
        Gets the contents of the previously defined redirector at a given path

        :param XRootD.client.FileSystem door: The door server to use for the listing
        :param str path: The full path, starting with ``/store/``, of the directory to list.
        :returns: A bool indicating the success, a list of directories, and a list of files.
                  See :py:func:`XRootDLister.list` for more details on the output.
        :rtype: bool, list, list
        """

        # FileSystem only works with ending slashes for some sites (not all, but let's be safe)
        if path[-1] != '/':
            path += '/'

        self.log.debug('Using door at %s to list directory %s', door.url, path)

        # http://xrootd.org/doc/python/xrootd-python-0.1.0/modules/client/filesystem.html#XRootD.client.FileSystem.dirlist
        status, dir_list = door.dirlist(path, flags=XRootD.client.flags.DirListFlags.STAT)

        directories = []
        files = []

        self.log.debug('For %s, directory listing good: %s', path, bool(dir_list))

        # Assumes the listing went well for now
        okay = True

        # If there's a directory listing, parse it
        if dir_list:
            for entry in dir_list.dirlist:
                if entry.statinfo.flags & XRootD.client.flags.StatInfoFlags.IS_DIR:
                    directories.append((entry.name.lstrip('/'), entry.statinfo.modtime))
                else:
                    files.append((entry.name.lstrip('/'), entry.statinfo.size,
                                  entry.statinfo.modtime))

        # If status isn't perfect, analyze the error
        if not status.ok:

            self.log.warning('While listing %s: %s', path, status.message)

            error_code = self.error_re.search(status.message).group(1)

            # Retry certain error codes if there's no dir_list
            # Don't bother with 3010 at the moment because there's that Hadoop bug
            okay = error_code == '3010' or \
                (bool(dir_list) if error_code in ['!', '3005'] else False)

            self.log.debug('Error code: %s', error_code)
            self.log.debug('Directory List: %s', dir_list)
            self.log.debug('Okay: %i', okay)

        self.log.debug('From %s returning status %i with %i directories and %i files.',
                       path, okay, len(directories), len(files))

        return okay, directories, files

    def list(self, path, retries=0):
        """
        Return the directory contents at the given path.
        The ``list`` member is expected of every object passed to :py:mod:`datatypes`.

        :param str path: The full path, starting with ``/store/``, of the directory to list.
        :param int retries: Number of attempts so far
        :returns: A bool indicating the success, a list of directories, and a list of files.
                  The list of directories consists of tuples of (directory name, mod time).
                  The list of files consistents of tuples of (file name, size, mod time).
                  The modification times are in seconds from epoch and the file size is in bytes.
        :rtype: bool, list, list
        """

        if retries == self.tries:
            self.log.error('Giving up on %s due to too many retries', path)
            return False, [], []

        try:
            # Try with primary door
            okay, directories, files = self.ls_directory(self.primary_conn, path)

            # We could add sleep, reconnecting and other error handling here, if desired
            if not okay:
                # Try with backup door
                okay, directories, files = self.ls_directory(self.backup_conn, path)

                okay &= (not self.do_both)
            elif self.do_both:

                okay_back, directories_back, files_back = \
                    self.ls_directory(self.backup_conn, path)

                okay &= okay_back
                directories = list(set(directories + directories_back))
                files = list(set(files + files_back))

        except timeout_decorator.TimeoutError:
            self.log.warning('Directory %s timed out.', path)

            # Reconnect

            # First try to get the list of doors that are not connected in this instance
            _, door_list = config.get_redirector(
                self.site,
                list(
                    itertools.chain.from_iterable(
                        [re.search(r'root://((.*):\d*)/', str(conn.url)).group(1, 2) for conn in \
                             [self.primary_conn, self.backup_conn]]
                        )
                    )
                )

            # If we get any, reconnect
            if door_list:

                if len(door_list) == 1:
                    door_list.extend(door_list)

                use_doors = random.sample(door_list, 2)

                self.primary_conn = XRootD.client.FileSystem(use_doors[0])
                self.backup_conn = XRootD.client.FileSystem(use_doors[1])

            # Otherwise, swap urls
            else:
                backup_url = str(self.backup_conn.url)
                self.primary_conn = XRootD.client.FileSystem(backup_url)
                self.backup_conn = XRootD.client.FileSystem(str(self.primary_conn.url))

            return self.list(path, retries + 1)

        return okay, directories, files


@cache_tree('ListAge', 'remotelisting')
def get_site_tree(site):
    """
    Get the information for a site, from XRootD or a cache.

    :param str site: The site name
    :returns: The site directory listing information
    :rtype: ConsistencyCheck.datatypes.DirectoryInfo
    """

    # Get the redirector for a site
    # The redirector can be used for a double check (not implemented yet...)
    # The redir_list is used for the original listing

    balancer, door_list = config.get_redirector(site)
    LOG.debug('Full redirector list: %s', door_list)

    # Bool to determine if using both doors in each connection
    do_both = bool(site in config.config_dict().get('BothList', []))

    min_threads = config.config_dict().get('MinThreads', 0)

    if site in config.config_dict().get('UseLoadBalancer', []):
        min_threads = 1
        door_list = [balancer]

    while min_threads > (len(door_list) + 1)/2:
        if do_both or len(door_list) % 2:
            door_list.extend(door_list)
        else:
            # If even number of redirectors and not using both, stagger them
            door_list.extend(door_list[1:])
            door_list.append(door_list[0])

    # Add the first door to the end, in case we have an odd number of doors
    door_list.append(door_list[0])

    # Create DirectoryInfo for each directory to search (set in configuration file)
    # The search is done with XRootDLister objects that have two doors and the thread
    # number as initialization arguments.
    directories = [
        datatypes.create_dirinfo(
            '/store/', directory, XRootDLister,
            [(prim, back, site, thread_num, do_both) for prim, back, thread_num in \
                 zip(door_list[0::2], door_list[1::2], range(len(door_list[1::2])))]) \
            for directory in config.config_dict().get('DirectoryList', [])
        ]

    # Merge the DirectoryInfo
    info = datatypes.DirectoryInfo(name='/store', to_merge=directories)

    # Return the DirectoryInfo
    return info
