#!/usr/bin/python
#   Copyright (C) 2013 Red Hat, Inc.
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

from optparse import OptionParser, OptionGroup
import os.path
import logging
import threading

from aws_utils import EBSHelper, AMIHelper
import disk_utils
import anaconda_test

branch_release = 19

def get_opts():
    usage="""%prog [ecpu] a|n|r|t N|R|T

This script tests Anaconda in EC2."""
    parser = OptionParser(usage=usage)
    anagroup = OptionGroup(parser, 'Anaconda Source',
        'Decide where we get the Anaconda bits. You must pick one of these options.')
    anagroup.add_option('-a', '--ami', help='Use an already uploaded AMI')
    anagroup.add_option('-n', '--anaconda-nightly', default=False,
        action='store_true',
        help='Use the latest Fedora %s nightly Anaconda' % branch_release)
    anagroup.add_option('-r', '--anaconda-release', metavar='FedoraRelease',
        help='Use the Anaconda from a particular Fedora release (15+)')
    anagroup.add_option('-t', '--anaconda-tree', metavar='TreeURL',
        help='Use an arbitrary installation tree URL to get Anaconda')
    parser.add_option_group(anagroup)
    instgroup = OptionGroup(parser, 'Installation Tree Source',
        'Choose where to get the tree of packages to install. You must choose one of these as well.')
    instgroup.add_option('-N', '--inst-nightly', default=False,
        action='store_true',
        help='Use the latest Fedora %s nightly installation tree' % branch_release)
    instgroup.add_option('-R', '--inst-release', metavar='FedoraRelease',
        help='Use the installation tree from a particular release (15+)')
    instgroup.add_option('-T', '--inst-tree', metavar='TreeURL',
        help='Use an arbitrary installation tree URL')
    parser.add_option_group(instgroup)
    parser.add_option('-e', '--ec2-region', default='us-east-1',
        help='set an EC2 region (us-east-1)')
    parser.add_option('-c', '--test-case', default='all',
        help='Select a specific test by name to run')
    parser.add_option('-p', '--parameters', default='',
        help='Set the kernel parameters to be passed to Anaconda. Use a quoted string to pass multiple parameters.')
    parser.add_option('-u', '--updates', default=None,
        help='Specify a URL to an updates.img and include it')
    opts = parser.parse_args()[0] # no positional arguments
    if opts.updates:
        opts.parameters += ' updates=%s' % opts.updates
    if opts.anaconda_nightly:
        opts.anaconda_tree = 'http://dl.fedoraproject.org/pub/fedora/linux/development/%s/x86_64/os/' % branch_release
    elif opts.anaconda_release:
        opts.anaconda_tree = 'http://alt.fedoraproject.org/pub/fedora/linux/releases/%s/Fedora/x86_64/os/' % anaconda_release
    elif opts.anaconda_tree or opts.ami:
        pass
    else:
        parser.error('You must specify -a, -n, -r or -t for Anaconda bits')
    if opts.inst_nightly:
        opts.inst_tree = 'http://dl.fedoraproject.org/pub/fedora/linux/development/%s/x86_64/os/' % branch_release
    elif opts.inst_release:
        opts.inst_tree = 'http://alt.fedoraproject.org/pub/fedora/linux/releases/%s/Fedora/x86_64/os/' % inst_release
    elif opts.inst_tree:
        pass
    else:
        parser.error('You must specify -N, -R or -T for an installation tree')
    return opts

results = {}
result_lock = threading.Lock()

def run_test(helper, ami, test):
    testresult = helper.launch_wait_snapshot(ami, test.ks, test.resources)
    result_lock.acquire()
    results[test.name] = testresult
    result_lock.release()

def review_results():
    fails = 0
    for test, result in results.items():
        log.info(result)
        if result['status'] == 'error':
            fails += 1
    sys.exit(fails)

if __name__ == '__main__':
    opts = get_opts()
    image = disk_utils.construct_image(opts.anaconda_tree, opts.parameters)
    ebs_helper = EBSHelper(opts.ec2_region)
    ami_helper = AMIHelper(opts.ec2_region)
    snapshot = ebs_helper.safe_upload_and_shutdown(image)   # upload it
    seed_ami = ami_helper.register_ebs_ami(snapshot) # "stage 1" AMI
    threads = []
    tests = anaconda_test.get_test(opts.test_case) # 'all' means get all of them
    for test in tests:
        threads.append(threading.Thread(
            target=run_test,
            args=(ami_helper, seed_ami, test),
            name=test.name))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    review_results(results)
