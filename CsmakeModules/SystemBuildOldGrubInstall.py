# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
from CsmakeModules.SystemBuildGrubInstall import SystemBuildGrubInstall
import glob
import os
import os.path
import stat
import subprocess

class SystemBuildOldGrubInstall(SystemBuildGrubInstall):
    """Purpose: Install grub using grub 0.97 on the given system
                system must be mounted.
       Implements: SystemBuildGrubInstall
       Type: Module   Library: csmake-system-build
       Phases:
           build, system_build
       Options:
           system - The SystemBuild system to make bootable
           kernel - (OPTIONAL) name of the kernel bootstrap (glob format)
                    Default: vmlinuz*
                    Module will fail if more than one match exists
           initrd - (OPTIONAL) name of the initial filesystem (glob format)
                    Default: initramfs*
                    Module will fail if more than one match exists
           params - (OPTIONAL) kernel parameters to add
                    Default: <nothing>
       Note:
           This module currenly assumes that the boot/root is
           hd0 and /dev/sda on the targeted system
           Also, this module uses (abuses) the /dev/[hs]d[a-z] linux convention
           in order to work around the fact that legacy grub cannot handle
           loop devices.  The algorithm used will be to start assigning
           disks from /dev/hdz and back (hdy, etc) if /dev/hd* is unused
           by the host system.  If it is used, and /dev/sd* is unused, then
           the sd* convention will be used also starting from z and proceeding
           backward.  If both hd* and sd* are in use on the system, the hdz and
           following will be utilized since it is much less likely to be used
           beyond hdd (since most IDE PATA controllers only support channel
           0 and 1 slave and master and the hd* convention is usually associated
           with the native IDE PATA drivers.

           If there is not enough room for this module to abuse the /dev/[hs]d*
           convention to its own ends, the module will fail.
    """

    REQUIRED_OPTIONS = ['system']

    GRUB_CONFIG_FILE = "boot/grub/grub.conf"
    GRUB_MAP_FILE = "boot/grub/device.map"
    GRUB_OPTIONS= ['--no-floppy' ]

    BOILERPLATE_GRUB_CONF="""
default=0
timeout=10

title CentOS
  root %s
  kernel %s ro root=%s %s
  initrd %s """

    ETC_MTAB_FILE = "etc/mtab"

    def _prepareForGrubInstall(self):
        #Does /dev/hd* exist?
        chosenpath = '/dev/hd'
        currentdrive = 'z'
        currentgrub = 0
        if os.path.exists('/dev/hda'):
            if not os.path.exists('/dev/sda'):
                chosenpath = '/dev/sd'

        self._oldGrubDiskMappings = {}
        self._deviceMapEntries = []
        self._mtabEntries = []
        self._createdDevEntries = []
        self._etcdirmask = None
        self._mtabfilemask = None
        self._systemPathToMtab = None
        self._systemPathToMap = None

        try:
            #Create fake dev entries that legacy grub can handle pointing
            # to the system we're building.
            for name, disk in self.systemEntry['disks'].items():
                if disk['real']:
                    currentdev = '%s%s' % (chosenpath, currentdrive)
                    if os.path.exists(currentdev):
                        errormsg = "%s is required for use to install grub, but already exists on the system" % currentdev
                        self.log.error(errormsg)
                        raise ValueError(errormsg)
                    devstat = os.stat(disk['device'])
                    if not stat.S_ISBLK(devstat.st_mode):
                        errormsg = "%s is not a block device" % disk['device']
                        self.log.error(errormsg)
                        raise ValueError(errormsg)
                    devmajor = os.major(devstat.st_rdev)
                    devminor = os.minor(devstat.st_rdev)
                    self._createdDevEntries.append(currentdev)
                    subprocess.check_call(
                        [ 'sudo', 'mknod', currentdev, 'b', str(devmajor), str(devminor) ],
                        stdout=self.log.out(),
                        stderr=self.log.err() )
                    self._oldGrubDiskMappings[disk['device']] = currentdev
                    self._deviceMapEntries.append(('hd%d'%currentgrub, currentdev))
                    for name, part in disk['partitions'].items():
                        currentPart = "%s%d" % (currentdev, part['number'])
                        partstat = os.stat(part['device'])
                        if not stat.S_ISBLK(partstat.st_mode):
                            errormsg = "%s is not a block device" % part['device']
                            self.log.error(errormsg)
                            raise ValueError(errormsg)
                        partmajor = os.major(partstat.st_rdev)
                        partminor = os.minor(partstat.st_rdev)
                        self._createdDevEntries.append(currentPart)
                        subprocess.check_call(
                            [ 'sudo', 'mknod' , currentPart, 'b', str(partmajor), str(partminor) ],
                            stdout=self.log.out(),
                            stderr=self.log.err() )
                        self._oldGrubDiskMappings[part['device']] = currentPart
                    currentgrub += 1
                    currentdrive = chr(ord(currentdrive) - 1)
            for mountpt, device, fstype, fstabid in self.systemEntry['filesystem'].values():
                mtabDevice = device
                if mtabDevice in self._oldGrubDiskMappings:
                    mtabDevice = self._oldGrubDiskMappings[mtabDevice]
                self._mtabEntries.append("%s %s %s rw 0 0" % (
                    mtabDevice,
                    mountpt,
                    fstype ) )

            self._systemPathToMtab = os.path.join(
                self.systemPartition,
                self.ETC_MTAB_FILE )
            self._systemPathToEtc, _ = os.path.split(
                self._systemPathToMtab )

            self._ensureDirectoryExists(self._systemPathToMtab)
            self._etcdirmask = self._sudo_change_file_perms(
                self._systemPathToEtc, '777')
            try:
                self._mtabfilemask = self._sudo_change_file_perms(
                    self._systemPathToMtab, '666')
            except OSError:
                self._mtabfilemask = '664'

            with open(self._systemPathToMtab, 'w') as mtab:
                mtab.write('\n'.join(self._mtabEntries))

        except:
            self._cleanUpPostGrubInstall()
            raise

    def _cleanUpPostGrubInstall(self):
        #Undo fake [hs]d* files
        self.log.debug("Cleaning up dev entries: %s", str(self._createdDevEntries))
        for devfile in self._createdDevEntries:
            subprocess.call(
                [ 'sudo', 'rm', '-f', devfile ],
                stdout = self.log.out(),
                stderr = self.log.err())

        #XXX: Revisit - ensure cleanup happens
        return

        #Undo mtab
        if self._systemPathToMtab is not None:
            subprocess.call(
                [ 'sudo', 'rm', '-f', self._systemPathToMtab ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            with open(self._systemPathToMtab, 'w') as mtab:
                mtab.write('')
        if self._mtabfilemask is not None:
            self._sudo_change_file_perms(self._systemPathToMtab, self._mtabfilemask)
        if self._etcdirmask is not None:
            self._sudo_change_file_perms(self._systemPathToEtc, self._etcdirmask)

        #Remove device.map file
        if self._systemPathToMap is not None:
            subprocess.call(
                [ 'sudo', 'rm', '-f', self._systemPathToMap ],
                stdout = self.log.out(),
                stderr = self.log.err() )

    def _generateGrubConfig(self):
        #Write out a grub.conf
        pathToConfig = self.GRUB_CONFIG_FILE
        systemPathToConfig = os.path.join(
            self.systemPartition,
            pathToConfig )

        #Write out a device map
        pathToMap = self.GRUB_MAP_FILE
        self._systemPathToMap = os.path.join(
            self.systemPartition,
            pathToMap )

        self._ensureDirectoryExists(systemPathToConfig)
        self._ensureDirectoryExists(self._systemPathToMap)

        mapEntries = []
        grubRootDrive = "(hd%d)" % self.systemDeviceInfo['disk']['number']
        grubRoot = grubRootDrive.rstrip(')')

        mappedSystemDevice = self.systemDevice
        if self.systemDevice in self._oldGrubDiskMappings:
            mappedSystemDevice = self._oldGrubDiskMappings[self.systemDevice]
        mapEntries.append( (
            grubRootDrive,
            mappedSystemDevice ) )

        if self.systemDeviceInfo['partition'] is not None:
            grubRoot += ',%d)' % (self.systemDeviceInfo['partition']['number'] - 1)
        else:
            grubRoot += ')'

        if not self.systemPathToSystemDevice.endswith('boot'):
            grubRoot += '/boot'

        #We just ensured that grub's root will be in the right place for boot
        #so, create a localBootRoot path to help us locally, but grub paths
        #will want to just use systemPartition.
        localBootRoot = os.path.join(self.systemPartition, 'boot')

        #Find the names of the kernel and initrd (assuming under <root>/boot)
        kernel = 'vmlinuz*'
        if 'kernel' in self.options:
            kernel = self.options['kernel']
        bootentries = glob.glob(os.path.join(
            localBootRoot,
            kernel))
        if len(bootentries) > 1:
            self.log.error("Searching for kernel file '%s' found multiple entries: %s", kernel, ', '.join(bootentries))
            return False
        kernelfile = os.path.relpath(bootentries[0], localBootRoot).strip('.')
        if not kernelfile.startswith('/'):
           kernelfile = '/' + kernelfile
        
        initrd = 'initramfs*'
        if 'initrd' in self.options:
            initrd = self.options['initrd']
        bootentries = glob.glob(os.path.join(
            localBootRoot,
            initrd))
        if len(bootentries) > 1:
            self.log.error("Searching for initrd file '%s' found multiple entries: %s", initrd, ', '.join(bootentries))
            return False
        initrdfile = os.path.relpath(bootentries[0], localBootRoot).strip('.')
        if not initrdfile.startswith('/'):
            initrdfile = '/' + initrdfile

        kernelParams = ''
        if 'params' in self.options:
            kernelParams = self.options['params']

        dirToConfig, _ = os.path.split(systemPathToConfig)
        self._ensureDirectoryExists(systemPathToConfig)

        self._grubdirmask = self._sudo_change_file_perms(dirToConfig, '777')
        self._conffilemask = None
        if os.path.exists(systemPathToConfig):
            self._conffilemask = self._sudo_change_file_perms(systemPathToConfig, '666')
        #Write out the config file
        with open(systemPathToConfig,'w') as cfg:
            cfg.write(self.BOILERPLATE_GRUB_CONF % (
                grubRoot,
                kernelfile,
                self.rootTabId,
                kernelParams,
                initrdfile ) )

        #Generate the map information
        with open(self._systemPathToMap, 'w') as cfg:
            for entry in mapEntries:
                cfg.write("%s\t%s\n" % entry)

        if self._conffilemask is not None:
            self._sudo_change_file_perms(systemPathToConfig, self._conffilemask)
        self._sudo_change_file_perms(dirToConfig, self._grubdirmask)

        #Transition the system device to the fake device
        if self.systemDevice in self._oldGrubDiskMappings:
            self.systemDevice = self._oldGrubDiskMappings[self.systemDevice]
        
        return True
