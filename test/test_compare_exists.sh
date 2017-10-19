#! /bin/bash

#
# This file checks that prod/compare.py exists.
# If it no longer exists, delete this file, and
#
#       !!!UPDATE THE README!!!
#
# for documentation on the production script
#
# Now it also checks for prod/run_checks.sh!
#

test -f $(dirname $0)/../prod/compare.py || exit 2
test -f $(dirname $0)/../prod/run_checks.sh || exit 4
