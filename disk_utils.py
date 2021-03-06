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
import os
import pycurl
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

def _generate_boot_content(url, dest_dir, cmdline):
    """
    Insert kernel, ramdisk and syslinux.cfg file in dest_dir
    source from url
    """
    for content in ('vmlinuz', 'initrd.img'):
        destination = os.path.join(dest_dir, content)
        source = url + "images/pxeboot/%s" % content
        print 'Downloading %s' % content
        http_download_file(source, destination)

    pvgrub_conf="""# This file is for use with pv-grub;
# legacy grub is not installed in this image
default=0
timeout=0
title Anaconda install inside of EC2
        root (hd0,0)
        kernel /boot/grub/vmlinuz %s
        initrd /boot/grub/initrd.img
""" % cmdline
    f = open(os.path.join(dest_dir, "menu.lst"), "w")
    f.write(pvgrub_conf)
    f.close()

def http_download_file(url, filename):
    fd = os.open(filename,os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    try:
        _http_download_file(url, fd, True)
    finally:
        os.close(fd)

def _http_download_file(url, fd, show_progress):
    """
    Function to download a file from url to file descriptor fd.
    """
    class Progress(object):
        def __init__(self):
            self.last_k = -1

    def _data(buf):
        """
        Function that is called back from the pycurl perform() method to
        actually write data to disk.
        """
        os.write(fd, buf)

    progress = Progress()
    c = pycurl.Curl()
    c.setopt(c.URL, url)
    c.setopt(c.CONNECTTIMEOUT, 5)
    c.setopt(c.WRITEFUNCTION, _data)
    c.setopt(c.FOLLOWLOCATION, 1)
    c.perform()
    c.close()

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
        if filename == 'anaconda-seed.raw':
            continue
        g.upload(os.path.join(contentdir,filename),"/boot/grub/" + filename)
    g.sync()

def construct_image(tree_url, parameters):
    """
    Generate a .raw file, this is the entry point function from main.
    The steps are:
        create an ext2 image
        generate some required configuration in the image (like menu.lst)
        copy in the anaconda bits from the install tree
    """
    tmp_content_dir = mkdtemp()
    name = os.path.join(tmp_content_dir, 'anaconda-seed.raw')
    _create_ext2_image(name, image_size=(1024*1024*200))
    _generate_boot_content(tree_url, tmp_content_dir, parameters)
    _copy_content_to_image(tmp_content_dir, name)
    return name
