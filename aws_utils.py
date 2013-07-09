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

# Significant portions derived from Image Factory - http://imgfac.org/

import boto.ec2
import random
import logging
import process_utils
import re
import os.path
from boto.exception import EC2ResponseError
from tempfile import NamedTemporaryFile
from time import sleep
from boto.ec2.blockdevicemapping import EBSBlockDeviceType, BlockDeviceMapping

# Boto is very verbose - shut it up
logging.getLogger('boto').setLevel(logging.INFO)

# Fedora 18 - i386 - EBS backed themselves
UTILITY_AMIS = { 'us-east-1':      [ 'ami-6f640c06', 'sudo', 'ec2-user' ],
                 'us-west-2':      [ 'ami-67930257', 'sudo', 'ec2-user' ],
                 'us-west-1':      [ 'ami-634f6126', 'sudo', 'ec2-user' ],
                 'eu-west-1':      [ 'ami-2d819059', 'sudo', 'ec2-user' ],
                 'ap-southeast-1': [ 'ami-f8357baa', 'sudo', 'ec2-user' ],
                 'ap-southeast-2': [ 'ami-f5d340cf', 'sudo', 'ec2-user' ],
                 'ap-northeast-1': [ 'ami-51bc3550', 'sudo', 'ec2-user' ],
                 'sa-east-1':      [ 'ami-d2e84dcf', 'sudo', 'ec2-user' ] }

# hd00 style (full disk image) v1.03
PVGRUB_AKIS =  { 'us-east-1':      { 'i386':'aki-b2aa75db' ,'x86_64':'aki-b4aa75dd' },
                 'us-west-2':      { 'i386':'aki-f637bac6' ,'x86_64':'aki-f837bac8' },
                 'us-west-1':      { 'i386':'aki-e97e26ac' ,'x86_64':'aki-eb7e26ae' },
                 'eu-west-1':      { 'i386':'aki-89655dfd' ,'x86_64':'aki-8b655dff' },
                 'ap-southeast-1': { 'i386':'aki-f41354a6' ,'x86_64':'aki-fa1354a8' },
                 'ap-southeast-2': { 'i386':'aki-3f990e05' ,'x86_64':'aki-3d990e07' },
                 'ap-northeast-1': { 'i386':'aki-3e99283f' ,'x86_64':'aki-40992841' },
                 'sa-east-1':      { 'i386':'aki-ce8f51d3' ,'x86_64':'aki-c88f51d5' } }

resource_tag = 'anaconda-test'

def safe_call(call, args, log, die=False):
    """
    Safely call an EC2 API and catch an error if something happens.
    """
    #log.debug('calling an EC2 API: %s(%s)' % (call.func_name, args))
    retval = 'ERROR'
    try:
        retval = call(*args)
    except EC2ResponseError, e:
        log.warning('Caught a %s when calling %s(%s). Error: %s' %
            (type(e), call.func_name, args, e))
    except Exception, e:
        log.warning('Caught a %s in the dirty except' % type(e))
        log.error('Error message: %s' % e)
    if retval == 'ERROR' and die:
        raise RuntimeError('safe_call blew up')
    return retval

def wait_for_ec2_instance_state(instance, log, final_state='running', timeout=300):
    for i in range(timeout):
        if i % 10 == 0:
            log.debug(
                "Waiting for EC2 instance to enter state (%s): %d/%d" %
                (final_state, i, timeout))
            request = safe_call(instance.update, [], log)
            if type(request) == Exception:
                safe_call(instance.terminate, [], log)
                break
        if instance.state == final_state:
            break
        sleep(1)
    if instance.state != final_state:
        safe_call(instance.terminate, [], log)
        raise Exception("Instance failed to start after %d seconds" % timeout)

class AMIHelper(object):

    def __init__(self, ec2_region):
        super(AMIHelper, self).__init__()
        self.log = logging.getLogger('%s.%s' %
            (__name__, self.__class__.__name__))
        try:
            self.region = boto.ec2.get_region(ec2_region)
            self.conn = self.region.connect()
        except Exception as e:
            self.log.error("Exception while attempting to connect to EC2")
            raise
        self.security_group = None
        self.instance = None

    def register_ebs_ami(self, snapshot_id, arch='x86_64', default_ephem_map=True, img_name=None, img_desc=None):
        # register against snapshot
        try:
            aki=PVGRUB_AKIS[self.region.name][arch]
        except KeyError:
            raise Exception("Unable to find pvgrub hd00 AKI for %s, arch (%s)" %
                (self.region.name, arch))
        if not img_name:
            rand_id = random.randrange(2**32)
            # These names need to be unique, hence the pseudo-uuid
            img_name='EBSHelper AMI - %s - uuid-%x' % (snapshot_id, rand_id)
        if not img_desc:
            img_desc='Created directly from volume snapshot %s' % snapshot_id

        self.log.debug("Registering %s as new EBS AMI" % snapshot_id)
        ebs = EBSBlockDeviceType()
        ebs.snapshot_id = snapshot_id
        ebs.delete_on_termination = True
        block_map = BlockDeviceMapping()
        block_map['/dev/sda'] = ebs
        # The ephemeral mappings are automatic with S3 images
        # For EBS images we need to make them explicit
        # These settings are required to make the same fstab work on both S3
        # and EBS images
        if default_ephem_map:
            e0 = EBSBlockDeviceType()
            e0.ephemeral_name = 'ephemeral0'
            e1 = EBSBlockDeviceType()
            e1.ephemeral_name = 'ephemeral1'
            block_map['/dev/sdb'] = e0
            block_map['/dev/sdc'] = e1
        result = self.conn.register_image(
            name=img_name, description=img_desc, architecture=arch,
            kernel_id=aki, root_device_name='/dev/sda',
            block_device_map=block_map)
        sleep(10)
        new_amis = self.conn.get_all_images([ result ])
        new_amis[0].add_tag('Name', resource_tag)

        return str(result)

    def launch_wait_snapshot(self, ami, user_data, img_size=10, inst_type='m1.small', img_name=None, img_desc=None, remote_access_cmd=None):
        if not img_name:
            rand_id = random.randrange(2**32)
            # These names need to be unique, hence the pseudo-uuid
            img_name = 'EBSHelper AMI - %s - uuid-%x' % (ami, rand_id)
        if not img_desc:
            img_desc = 'Created from modified snapshot of AMI %s' % (ami)
        try:
            ami = self._launch_wait_snapshot(
                ami, user_data, img_size, inst_type, img_name, img_desc, remote_access_cmd)
        finally:
            if self.security_group:
                safe_call(self.security_group.delete, [], self.log)
        return ami

    def _launch_wait_snapshot(self, ami, user_data, img_size=10, inst_type='m1.small', img_name=None, img_desc=None, remote_access_command=None):
        rand_id = random.randrange(2**32)
        # Modified from code taken from Image Factory
        # Create security group
        security_group_name = "ebs-helper-vnc-tmp-%x" % (rand_id)
        security_group_desc = "Temporary security group with SSH access generated by EBSHelper python object"
        self.log.debug("Creating temporary security group (%s)" %
            security_group_name)
        self.security_group = self.conn.create_security_group(
            security_group_name, security_group_desc)
        self.security_group.authorize('tcp', 22, 22, '0.0.0.0/0')
        self.security_group.authorize('tcp', 5900, 5950, '0.0.0.0/0')
        self.security_group.add_tag('Name', resource_tag)
        ebs_root = EBSBlockDeviceType()
        ebs_root.size=img_size
        ebs_root.delete_on_termination = True
        block_map = BlockDeviceMapping()
        block_map['/dev/sda'] = ebs_root

        # Now launch it
        self.log.debug("Starting %s in %s with as %s" %
            (ami, self.region.name, inst_type))
        reservation = self.conn.run_instances(ami, max_count=1,
            instance_type=inst_type, user_data=user_data,
            security_groups=[security_group_name], block_device_map=block_map)
        if len(reservation.instances) == 0:
            raise Exception("Attempt to start instance failed")
        self.instance = reservation.instances[0]
        wait_for_ec2_instance_state(self.instance, self.log,
            final_state='running', timeout=300)
        self.instance.add_tag('Name', resource_tag)
        self.log.debug("Instance (%s) is now running" % self.instance.id)
        self.log.debug("Public DNS will be: %s" % self.instance.public_dns_name)
        self.log.debug("Now waiting up to 30 minutes for instance to stop")

        wait_for_ec2_instance_state(self.instance, self.log,
            final_state='stopped', timeout=1800)

        # Snapshot
        self.log.debug(
            "Creating a new EBS image from completed/stopped EBS instance")
        new_ami_id = self.conn.create_image(self.instance.id, img_name,
            img_desc)
        self.log.debug("boto creat_image call returned AMI ID: %s" % new_ami_id)
        self.log.debug("Waiting for newly generated AMI to become available")
        # As with launching an instance we have seen occasional issues when
        # trying to query this AMI right away - give it a moment to settle
        sleep(10)
        new_amis = self.conn.get_all_images([ new_ami_id ])
        new_ami = new_amis[0]
        timeout = 120
        interval = 10
        for i in range(timeout):
            new_ami.update()
            if new_ami.state == "available":
                new_ami.add_tag('Name', resource_tag)
                break
            elif new_ami.state == "failed":
                raise Exception("Amazon reports EBS image creation failed")
            self.log.debug(
                "AMI status (%s) is not 'available' - [%d of %d seconds]" %
                (new_ami.state, i * interval, timeout * interval))
            sleep(interval)
        self.log.debug("Terminating/deleting instance")
        self.instance.terminate()
        if new_ami.state != "available":
            raise Exception("Failed to produce an AMI ID")
        self.log.debug("SUCCESS: %s is now available for launch" % new_ami_id)
        return new_ami_id

class EBSHelper(object):

    def __init__(self, ec2_region, utility_ami=None, command_prefix=None, user='root'):
        super(EBSHelper, self).__init__()
        self.log = logging.getLogger(
            '%s.%s' % (__name__, self.__class__.__name__))
        try:
            self.region = boto.ec2.get_region(ec2_region)
            self.conn = self.region.connect()
        except Exception as e:
            self.log.error("Exception while connecting to EC2")
            raise
        if not utility_ami:
            self.utility_ami = UTILITY_AMIS[ec2_region][0]
            self.command_prefix = UTILITY_AMIS[ec2_region][1]
            self.user = UTILITY_AMIS[ec2_region][2]
        else:
            self.utility_ami = utility_ami
            self.command_prefix = command_prefix
            self.user = user
        self.instance = None
        self.security_group = None
        self.key_name = None
        self.key_file_object = None

    def safe_upload_and_shutdown(self, image_file):
        """
        Launch the AMI - terminate
        upload, create volume and then terminate
        """
        if self.instance:
            raise Exception(
                "Cannot have a running utility instance with Safe upload")
        self.start_ami()
        try:
            snapshot = self.file_to_snapshot(image_file)
        finally:
            safe_call(self.terminate_ami, (), self.log)
        return snapshot

    def start_ami(self):
        rand_id = random.randrange(2**32)
        # Modified from code taken from Image Factory
        # Create security group
        security_group_name = "ebs-helper-tmp-%x" % (rand_id)
        security_group_desc = "Temporary security group with SSH access generated by EBSHelper python object"
        self.log.debug("Creating temporary security group (%s)" %
            security_group_name)
        self.security_group = safe_call(self.conn.create_security_group,
            (security_group_name, security_group_desc), self.log, die=True)
        self.security_group.authorize('tcp', 22, 22, '0.0.0.0/0')
        self.security_group.add_tag('Name', resource_tag)

        # Create a use-once SSH key
        self.log.debug("Creating SSH key pair for image upload")
        # XXX: EC2 does not support tagging key pairs :(
        self.key_name = "ebs-helper-tmp-%x" % (rand_id)
        self.key = safe_call(self.conn.create_key_pair, (self.key_name,),
            self.log, die=True)
        # Shove into a named temp file
        self.key_file_object = NamedTemporaryFile()
        self.key_file_object.write(self.key.material)
        self.key_file_object.flush()
        self.log.debug("Temporary key is stored in (%s)" %
            (self.key_file_object.name))

        # Now launch it
        instance_type="m1.small"
        self.log.debug("Starting %s in %s as %s" %
            (self.utility_ami, self.region.name, instance_type))
        reservation = self.conn.run_instances(
            self.utility_ami, max_count=1, instance_type=instance_type,
            key_name=self.key_name, security_groups=[security_group_name])
        if len(reservation.instances) == 0:
            raise Exception("Attempt to start instance failed")
        self.instance = reservation.instances[0]
        wait_for_ec2_instance_state(self.instance, self.log,
            final_state='running', timeout=300)
        self.instance.add_tag('Name', resource_tag)
        self.wait_for_ec2_ssh_access(self.instance.public_dns_name,
            self.key_file_object.name)
        self.enable_root(self.instance.public_dns_name,
            self.key_file_object.name, self.user, self.command_prefix)

    def terminate_ami(self):
        # Terminate the AMI and delete all local and remote artifacts
        # Try very hard to do whatever is possible here and warn loudly if
        # something may have been left behind
        # Remove local copy of the key
        self.key_file_object.close()

        # Remove remote copy of the key
        if self.key_name:
            safe_call(self.conn.delete_key_pair, (self.key_name,), self.log)

        # Terminate the instance
        if self.instance:
            retval = safe_call(self.instance.terminate, (), self.log, die=True)
            timeout = 60
            interval = 5
            for i in range(timeout):
                safe_call(self.instance.update, (), self.log, die=True)
                if self.instance.state == "terminated" :
                    break
                elif i < timeout :
                    self.log.debug(
                        "Instance is not terminated [%s of %s seconds]" %
                        (i * interval, timeout * interval))
                    sleep(interval)

        # If we do have an instance it must be terminated before this can happen
        # That is why we put it last
        # Try even if we get an exception while doing the termination above
        if self.security_group:
            safe_call(self.security_group.delete, (), self.log)

    def file_to_snapshot(self, filename, compress=True):
        if not self.instance:
            raise Exception("You must start the utility instance first!")
        if not os.path.isfile(filename):
            raise Exception("Filename (%s) is not a file" % filename)
        filesize = os.path.getsize(filename)
        # Gigabytes, rounded up
        volume_size = int( (filesize/(1024 ** 3)) + 1 )
        self.log.debug("Creating %d GiB volume in (%s) to hold new image" %
            (volume_size, self.instance.placement))
        volume = self.conn.create_volume(volume_size, self.instance.placement) 

        # Volumes can sometimes take a very long time to create
        # Wait up to 10 minutes for now (plus the time taken for the upload
        # above)
        self.log.debug(
            "Waiting up to 600 seconds for volume (%s) to become available" %
            volume.id)
        for i in range(60):
            safe_call(volume.update, (), self.log, die=True)
            if volume.status == "available":
                volume.add_tag('Name', resource_tag)
                break
            self.log.debug(
                "Volume status (%s) - waiting for 'available': %d/600" %
                (volume.status, i*10))
            sleep(10)

        # Volume is now available, attach it
        safe_call(self.conn.attach_volume,
            (volume.id, self.instance.id, "/dev/sdh"), self.log, die=True)
        self.log.debug(
            "Waiting up to 120 seconds for volume (%s) to become in-use" %
            volume.id)
        for i in range(12):
            safe_call(volume.update, (), self.log, die=True)
            vs = volume.attachment_state()
            if vs == "attached":
                break
            self.log.debug(
                "Volume status (%s) - waiting for 'attached': %d/120" %
                (vs, i*10))
            sleep(10)

        # TODO: This may not be necessary but it helped with some funnies
        # observed during testing. At some point run a bunch of builds without
        # the delay to see if it breaks anything.
        self.log.debug("Waiting 20 seconds for EBS attachment to stabilize")
        sleep(20)

        # Decompress image into new EBS volume
        self.log.debug("Copying file into volume")

        # This is big and hairy - it also works, and avoids temporary storage
        # on the local and remote side of this activity
        command = 'gzip -c %s | ' % filename
        command += 'ssh -i %s -F /dev/null  -o ServerAliveInterval=30 -o StrictHostKeyChecking=no ' % self.key_file_object.name
        command += '-o ConnectTimeout=30 -o UserKnownHostsFile=/dev/null -o PasswordAuthentication=no '
        command += 'root@%s "gzip -d -c | dd of=/dev/xvdh bs=4k"' % self.instance.public_dns_name

        self.log.debug("Command will be:\n%s\n" % command)
        self.log.debug("Running.  This may take some time.")
        process_utils.subprocess_check_output([ command ], shell=True)

        # Sync before snapshot
        process_utils.ssh_execute_command(self.instance.public_dns_name,
            self.key_file_object.name, "sync")

        # Snapshot EBS volume
        self.log.debug("Taking snapshot of volume (%s)" % volume.id)
        snapshot = self.conn.create_snapshot(volume.id,
            'EBSHelper snapshot of file "%s"' % filename)

        # This can take a _long_ time - wait up to 20 minutes
        self.log.debug(
            "Waiting up to 1200 seconds for snapshot (%s) to become completed" %
            snapshot.id)
        for i in range(120):
            safe_call(snapshot.update, (), self.log, die=True)
            if snapshot.status == "completed":
                snapshot.add_tag('Name', resource_tag)
                break
            self.log.debug(
                "Snapshot progress(%s) - status (%s) is not 'completed': %d/1200" %
                (str(snapshot.progress), snapshot.status, i*10))
            sleep(10)
        self.log.debug("Successful creation of snapshot (%s)" % snapshot.id)
        self.log.debug("Detaching volume (%s)" % volume.id)
        safe_call(volume.detach, (), self.log)

        self.log.debug(
            "Waiting up to 120 seconds for %s to become detached (available)" %
            volume.id)
        for i in range(12):
            safe_call(volume.update, (), self.log, die=True)
            if volume.status == "available":
                break
            self.log.debug("Volume status (%s) - is not 'available': %d/120" %
                (volume.status, i*10))
            sleep(10)
        self.log.debug("Deleting volume")
        safe_call(volume.delete, (), self.log, die=True)
        return snapshot.id

    def wait_for_ec2_ssh_access(self, guestaddr, sshprivkey):
        self.log.debug("Waiting for SSH access to EC2 instance (User: %s)" %
            self.user)
        for i in range(300):
            if i % 10 == 0:
                self.log.debug("Waiting for EC2 ssh access: %d/300" % (i))
            try:
                process_utils.ssh_execute_command(guestaddr, sshprivkey,
                    "/bin/true", user=self.user)
                self.log.debug('reached the instance as %s using %s' %
                    (self.user, sshprivkey))
                break
            except:
                pass
            sleep(1)
        if i == 299:
            raise Exception(
                "Unable to gain ssh access after 300 seconds - aborting")

    def wait_for_ec2_instance_start(self, instance):
        self.log.debug("Waiting for EC2 instance to become active")
        for i in range(300):
            if i % 10 == 0:
                self.log.debug("Waiting for EC2 instance to start: %d/300" % i)
                retval = safe_call(instance.update, [], self.log)
                if type(retval) == Exception:
                    safe_call(self.instance.terminate, [], self.log)
                    break
            if instance.state == u'running':
                break
            sleep(1)

        if instance.state != u'running':
            self.status="FAILED"
            safe_call(self.instance.terminate, [], self.log)
            raise RuntimeException(
                "Instance failed to start after 300 seconds - stopping")

    def enable_root(self,guestaddr, sshprivkey, user, prefix):
        for cmd in ('mkdir -p /root/.ssh',
                    'chmod 600 /root/.ssh',
                    'cp -f /home/%s/.ssh/authorized_keys /root/.ssh' % user,
                    'chmod 600 /root/.ssh/authorized_keys'):
            process_utils.ssh_execute_command(
                guestaddr, sshprivkey, cmd, user=user, prefix=prefix)
        stdout, stderr, retcode = process_utils.ssh_execute_command(
            guestaddr, sshprivkey, '/bin/id')
        if not re.search('uid=0', stdout):
            raise Exception('Running /bin/id on %s as root: %s' %
                (guestaddr, stdout))
