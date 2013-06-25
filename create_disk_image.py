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

import guestfs
from optparse import OptionParser
import ozutil
import re
import shutil
import logging
import os
from tempfile import mkdtemp
from string import Template

def _create_ext2_image(image_file, image_size=(1024*1024*200)):
    """
    Create a 200M (default) disk image named image_file.
    """
    raw_fs_image=open(image_file,"w")
    raw_fs_image.truncate(image_size)
    raw_fs_image.close()
    g = guestfs.GuestFS()
    g.add_drive(image_file)
    g.launch()
    g.part_disk("/dev/sda","msdos")
    g.part_set_mbr_id("/dev/sda",1,0x83)
    g.mkfs("ext2", "/dev/sda1")
    g.part_set_bootable("/dev/sda", 1, 1)
    g.sync()
    #g.shutdown() needed?

def _generate_boot_content(url, dest_dir):
    """
    Insert kernel, ramdisk and syslinux.cfg file in dest_dir
    source from url
    """
    kernel_url = url + "images/pxeboot/vmlinuz"
    initrd_url = url + "images/pxeboot/initrd.img"
    cmdline = "ks=http://169.254.169.254/latest/user-data"
    kernel_dest = os.path.join(dest_dir,"vmlinuz")
    http_download_file(kernel_url, kernel_dest)
    initrd_dest = os.path.join(dest_dir,"initrd.img")
    http_download_file(initrd_url, initrd_dest)

    pvgrub_conf="""# This file is for use with pv-grub;
# legacy grub is not installed in this image
default=0
timeout=0
title Anaconda install inside of EC2
        root (hd0,0)
        kernel /boot/grub/vmlinuz %s
        initrd /boot/grub/initrd.img
""" % cmdline
    f = open(os.path.join(dest_dir, "menu.lst"),"w")
    f.write(pvgrub_conf)
    f.close()

def http_download_file(url, filename):
    fd = os.open(filename,os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    try:
        ozutil.http_download_file(url, fd, False, logging.getLogger())
    finally:
        os.close(fd)

def _copy_content_to_image(contentdir, target_image):
    """
    Copy all files in contentdir to the target image using guestfs.
    """
    g = guestfs.GuestFS()
    g.add_drive(target_image)
    g.launch()
    g.mount_options ("", "/dev/sda1", "/")
    g.mkdir_p("/boot/grub")
    for filename in os.listdir(contentdir):
        g.upload(os.path.join(contentdir,filename),"/boot/grub/" + filename)
    g.sync()

def _ks_extract_bits(ksfile):

    install_url = None
    console_password = None
    console_command = None
    poweroff = False
    distro = None

    for line in ksfile.splitlines():
        # Install URL lines look like this
        # url --url=http://download.devel.redhat.com/released/RHEL-5-Server/U9/x86_64/os/
        m = re.match("url.*--url=(\S+)", line)
        if m and len(m.groups()) == 1:
            install_url = m.group(1)
            continue

        # VNC console lines look like this
        # Inisist on a password being set
        # vnc --password=vncpasswd    
        m = re.match("vnc.*--password=(\S+)", line)
        if m and len(m.groups()) == 1:
            console_password = m.group(1)
            console_command = "vncviewer %s:1"
            continue

        # SSH console lines look like this
        # Inisist on a password being set
        # ssh --password=sshpasswd    
        m = re.match("ssh.*--password=(\S+)", line)
        if m and len(m.groups()) == 1:
            console_password = m.group(1)
            console_command = "ssh root@%s"
            continue

        # We require a poweroff after install to detect completion -
        # look for the line
        if re.match("poweroff", line):
            poweroff=True
            continue

    return (install_url, console_password, console_command, poweroff)


def do_pw_sub(ks_file, admin_password):
    f = open(ks_file, "r")
    working_ks = ""
    for line in f:
        working_ks += Template(line).safe_substitute(
            { 'adminpw': admin_password })
    f.close()
    return working_ks

def generate_install_image(ks_file, image_filename):
    """
    Generate a .raw file, this is the entry point function from main.
    The steps are:
        create an ext2 image
        generate some required configuration in the image (like menu.lst)
        copy in the anaconda bits from the install tree
    """
    working_kickstart = open(ks_file).read()
    (install_tree_url, console_password, console_command, poweroff) = \
        _ks_extract_bits(working_kickstart, distro)
    if not poweroff:
        raise Exception(
            "ERROR: supplied kickstart file must contain a 'poweroff' line")
    if not install_tree_url:
        raise Exception("ERROR: no install tree URL specified and could not extract one from the kickstart/install-script")

    _create_ext2_image(image_filename, image_size=(1024*1024*200))
    tmp_content_dir = mkdtemp()
    try:
        _generate_boot_content(install_tree_url, tmp_content_dir)
        _copy_content_to_image(tmp_content_dir, image_filename)
    finally:
        shutil.rmtree(tmp_content_dir)

def get_opts():
    usage='%prog [options] ksfile image-name'
    parser = OptionParser(usage=usage)
    opts, args = parser.parse_args()
    if len(args) != 2:
        parser.error('You must provide a kickstart file and image name')
    if not args[1].endswith('.raw'):
        args[1] += '.raw'
    if not os.path.exists(args[0]):
        parser.error('kickstart %s does not exist!' % args[0])
    return args[0], args[1]

if __name__ == "__main__":
    ksfile, imagename = get_opts()
    generate_install_image(ksfile, imagename)
