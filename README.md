Run the Anaconda installer in EC2
=================================

This is a fork of Ian McLeod's work that attempts to collect some code that
launches Anaconda based installs inside of EBS backed images in EC2. You can see
some of his related work on OpenStack:

https://github.com/redhat-openstack/image-building-poc/

I have added a few features to make this more useful to Anaconda testing such
as changing the kernel parameters and including an updates.img. I have also
dropped Ubuntu-related code since I have no intention of maintaining it for now.

Like Ian's repo this requires the boto EC2 bindings and libguestfs.

$ yum install python-libguestfs python-boto

## Example

### Create a local disk image that will boot Anaconda via pvgrub

    $ ./create_disk_image.py <install-tree-url> fedora_18.raw

The install tree URL will be used to extract the kernel and ramdisk
needed to bootstrap Anaconda. An updates.img can be used too.
These pieces are put into a disk image along with a valid pvgrub
menu.lst file.  This is all that is needed to launch Anaconda inside of an EC insance.


### Turn this image into an AMI

    $ ./ami_from_disk_image.py <ec2_key> <ec2_secret> ./fedora_18.raw

If successful this will return an AMI on a line that looks like this:

    Got AMI: ami-beefbeef

This AMI launches Anaconda and looks for a kickstart file at the EC2 user data URL.

NOTE: This AMI can now be used for repeated runs of the next step, provided the OS version
and architecture are the same.

### Launch this AMI, wait for the install to complete then capture the results as a new AMI

The next script will launch this AMI, pass the kickstart via user data and then wait
for the install to complete and the instance to shut down.  Once this is done it will
create a new AMI using the create image call from the EC2 API.

    $ ./install_on_ec2.py <ec2_region> <ec2_key> <ec2_secret> <ami_from_last_step> ./examples/fedora-18-jeos.ks <root_password>

Note that you do not need to use the same kickstart file for the first and last step.  
However, the OS version and architecture must match.  That is, if the initial ks.cfg
pointed to an F18 64 bit install source this last step will launch an F18 64 bit Anaconda
installer.

Once the install instance is running, the script above will report its public
DNS address.  The F18 example kickstart in this repo contains a "vnc" line to allow
you to watch the graphical installer as it is running.  To do this, run the following
command:

    $ vncviewer <public_hostname_from_above>:1

When asked for a password, use the same oneyou passed as <root_password> above.
The VNC session will close when the install is complete and the script will eventually
return an AMI.  This is the completed image.

