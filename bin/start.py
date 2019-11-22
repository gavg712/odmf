#!/usr/bin/env python

from odmf import odmf
import logging
import coloredlogs
import sys

if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    coloredlogs.install(level='DEBUG', stream=sys.stdout)
    odmf.cli()