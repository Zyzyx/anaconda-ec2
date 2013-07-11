#!/usr/bin/python
#   Copyright (C) 2013 Red Hat, Inc.
#   Copyright (C) 2013 Ian McLeod <imcleod@redhat.com>
#                      Jay Greguske <jgregusk@redhat.com>
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

from optparse import OptionParser
import os.path
import logging
from aws_utils import EBSHelper, AMIHelper

def get_opts():
    usage = """%prog [options] image_file

Create an AMI on EC2 from a bootable disk image."""
    parser = OptionParser(usage=usage)
    parser.add_option('-r', '--region', default='us-east-1',
        help='set an EC2 region (us-east-1)')
    opts, args = parser.parse_args()
    if len(args) != 1:
        parser.error('You must provide a disk image file')
    if not os.path.exists(args[0]):
        parser.error('Could not find %s' % args[0])
    return opts.region, args[0]

logging.basicConfig(level=logging.DEBUG, format='%(message)s')

if __name__ == '__main__':
    region, image_file = get_opts()
    ebs_helper = EBSHelper(region)
    snapshot = ebs_helper.safe_upload_and_shutdown(image_file)
    ami_helper = AMIHelper(region)
    ami = ami_helper.register_ebs_ami(snapshot)

print "Got AMI: %s" % ami
