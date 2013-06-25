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

import guestfs
from optparse import OptionParser
import ozutil
import shutil
import logging
import os
from tempfile import mkdtemp

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

def generate_install_image(install_tree_url, image_filename):
    """
    Generate a .raw file, this is the entry point function from main.
    The steps are:
        create an ext2 image
        generate some required configuration in the image (like menu.lst)
        copy in the anaconda bits from the install tree
    """
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
        parser.error('You must provide a kickstart file and an install tree')
    if not args[1].endswith('.raw'):
        args[1] += '.raw'
    return args[0], args[1]

if __name__ == "__main__":
    treeurl, imagename = get_opts()
    generate_install_image(treeurl, imagename)
