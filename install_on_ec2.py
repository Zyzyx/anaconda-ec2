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
%prog <ec2_key> <ec2_secret> <install_ami> <install_script>

Create an AMI on EC2 by running a native installer contained in a
pre-existing AMI."""
    parser = OptionParser(usage=usage)
    parser.add_option('-r', '--region', default='us-east-1',
        help='Set the EC2 region we are working in')
    options, args = parser.parse_args()
    if not os.path.exists(args[3]):
        parser.error('could not read %s!' % args[3])
    return options, args[0], args[1], args[2], args[3]

logging.basicConfig(level=logging.DEBUG, format='%(message)s')

if __name__ == '__main__':
    opts, key, secret, install_ami, install_script = get_opts()
    ami_helper = AMIHelper(opts.region, key, secret)
    user_data = open(install_script).read()
    install_ami = ami_helper.launch_wait_snapshot(install_ami, user_data, 10)
    print "Got AMI: %s" % install_ami
