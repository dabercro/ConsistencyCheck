#! /usr/bin/env python

"""
This simple script uses the
:py:func:`ConsistencyCheck.checkphedex.check_for_datasets` check on orphan files.
At the end of the check, datasets with more than one file at the site are printed again.
This is for easy parsing by eye.

:author: Daniel Abercrombie <dabercro@mit.edu>
"""

import sys

from ConsistencyCheck.checkphedex import check_for_datasets

if __name__ == '__main__':

    print ''

    for num, dataset in check_for_datasets(sys.argv[1], '%s_compare_orphan.txt' % sys.argv[1]):
        print num, dataset
