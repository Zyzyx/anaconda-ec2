#!/usr/bin/python
#   Copyright (C) 2013 Red Hat, Inc.
#   Copyright (C) 2013 Ian McLeod <imcleod@redhat.com>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import logging
from optparse import OptionParser
import os.path
from aws_utils import EBSHelper, AMIHelper

def get_opts():
    usage="""
%prog <install_ami> <kickstart>

Create an AMI on EC2 by running a native installer contained in a
pre-existing AMI."""
    parser = OptionParser(usage=usage)
    parser.add_option('-i', '--instance-type', default='m1.small',
        help='Choose an instance type to install in', dest='inst_type')
    parser.add_option('-r', '--region', default='us-east-1',
        help='Set the EC2 region we are working in')
    parser.add_option('-s', '--disk-size', default=10, type='int',
        help='Set the size in G of the disk Anaconda will install to')
    options, args = parser.parse_args()
    if len(args) != 2:
        parser.error('You must provide an AMI and a kickstart file')
    if not os.path.exists(args[1]):
        parser.error('could not read %s!' % args[1])
    return options, args[0], args[1]

logging.basicConfig(level=logging.DEBUG, format='%(message)s')

if __name__ == '__main__':
    opts, install_ami, kickstart = get_opts()
    ami_helper = AMIHelper(opts.region)
    user_data = open(kickstart).read()
    install_ami = ami_helper.launch_wait_snapshot(
        install_ami, user_data, int(opts.disk_size), opts.inst_type)
    print "Got AMI: %s" % install_ami
