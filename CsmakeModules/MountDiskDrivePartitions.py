# <copyright>
# (c) Copyright 2019 Cardinal Peak Technologies, LLC
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
from Csmake.CsmakeAspect import CsmakeAspect
import subprocess
import os.path
import fcntl
import glob

class MountDiskDrivePartitions(CsmakeAspect):
    """Purpose: Mount the Partitions of the disk drive for use/copy, etc.
                Should be using a PrepDiskDrive'ed file.
                This may be used as a regular section or an aspect
       NOTE: When used as a regular section (i.e., not an aspect)
             UnmountDiskDrivePartitions must be eventually specified.
       Library: csmake-system-build
       Phases:
           build - Will do a mount (UnmountDiskDrivePartitions required)
       JoinPoints:
           start__build - Will do a mount
           end__build - Will do an unmount
       Options:
           mounts - Directory to setup mounts
                    Partitions will be mounted with their respective labels
                    as the directories.  If labels cannot be ascertained,
                    then the directories will be numbered with respect
                    to their partition.
           drive - File representing the disk drive to loop mount
           system-label - (OPTIONAL) When specified, will bind mount
                                     requisite live system directories
                                     to the specified mountpoint label
                                     (e.g. /dev, etc.)
           tag - (OPTIONAL) allows for multiple mounts.
                            Each active mount needs a unique tag.
                            Default: <nothing>
           whole-disk - (OPTIONAL) When True, the file will be mounted
                                   as a single disk, under the 'mounts'
                                   directory.
                            Default: False
       Environment:
           Drops a '__MountDiskDrivePartitions__<tag>' entry in the environment
           with a dictionary containing at least:
               {'count' - number of mounts,
                'instance' - the section instance,
                'device' - the mounted device (i.e., /dev/loop0),
                'partitions' - dictionary of partition mount -> device,
                'system-partition' - tuple of {partition mount, device)}
    """

    REQUIRED_OPTIONS = ['mounts', 'drive']
    ENVKEY='__MountDiskDrivePartitions__'

    def _onExit(self):
        self._cleanUpMounts(True)

    def _killAllProcessesAt(self, root):
        #This will attempt to kill any running process at the given root
        #location.  This can help unjam systems with a stuck process on a
        #chroot
        procs = glob.glob("/proc/[0-9]*")
        for proc in procs:
            try:
                rootlink = subprocess.check_output(
                    ['sudo', 'readlink', os.path.join(proc, 'root') ] )
                if rootlink.strip() == root:
                    _, pid = os.path.split(proc)
                    subprocess.call(
                        ['sudo', 'kill', '-9', pid] )
            except:
                self.log.debug("%s couldn't be examined for root %s", proc, root)

    def _cleanUpMounts(self, force=False):
        if self.taggedEnvKey not in self.env.env and not force:
            self.log.error(
                "Attempting to unmount '%s' (tag: %s), but it is not mounted",
                self.options['drive'],
                self.options['tag'] if 'tag' in self.options else '<nothing>' )
            return False
        mountdict = None
        try:
            mountdict = self.env.env[self.taggedEnvKey]
            mountdict['count'] -= 1
            if mountdict['count'] > 0 and not force:
                self.log.info("'%s' still has %d mounts - not unmounting", mountdict['count'])
                return True
        except:
            self.log.exception("Proceeding - but, failed to get the mount count")
            self.log.warning("Attempting to unwind a partial mount")

        if mountdict is not None:
            #Switch to the instance that actually mounted.
            self = mountdict['instance']

        #Work backwards to clean out partial mounting
        mountedDevices = list(self.mountedDevices)
        mountedDevices.reverse()
        subprocess.call(
            ['sync'],
            stdout=self.log.out(),
            stderr=self.log.err() )
        for dev in mountedDevices:
            subprocess.call(
                ['sudo', 'fstrim', dev],
                stdout=self.log.out(),
                stderr=self.log.err())
            try:
                subprocess.check_call(
                    ['sudo', 'umount', dev],
                    stdout=self.log.out(),
                    stderr=self.log.err() )
            except:
               #Attempt killing the processes
               self._killAllProcessesAt(dev)
               try:
                   subprocess.check_call(
                       ['sudo', 'umount', dev],
                       stdout=self.log.out(),
                       stderr=self.log.err() )
               except:
                   subprocess.call(
                       ['sudo', 'umount', '-fl', dev],
                       stdout=self.log.out(),
                       stderr=self.log.err() )

        self.mountedDevices = []

        #Finally, clean up the loop.
        if self.loopbackDevice is not None:
            result = subprocess.call(
                ['sudo', 'losetup', '-d', self.loopbackDevice],
                stdout=self.log.out(),
                stderr=self.log.err() )
            if result != 0:
                self.log.warning("Couldn't remove loopback device")
        result = subprocess.call(
            ['sudo', 'ioctl', device, '19457'],
            stdout=self.log.out(),
            stderr=self.log.err())
        if result != 0:
            self.log.warning("Detaching lo device '%' failed", device)

        #mountdev = self.partitionMapping[dev]
        subprocess.call(
            ['fallocate', '-d', self.options['drive']],
            stdout=self.log.out(),
            stderr=self.log.err() )

        #Now, clean up the mount directory.  If this fails,
        #the umounts were not clean.
        if 'mounts' in self.options:
            umountsuccess = subprocess.call(
                """for x in `ls %s/*`
                   do
                       sudo rmdir $x
                   done""" % self.options['mounts'],
                shell=True,
                stdout=self.log.out(),
                stderr=self.log.err() )
            parentsuccess = subprocess.call(
                ['sudo', 'rmdir', self.options['mounts']],
                stdout=self.log.out(),
                stderr=self.log.err() )

            if umountsuccess != 0 or parentsuccess != 0:
                self.log.error("Removing mountpoint directory failed - check mounts")
        try:
            self.log.debug("Removing '%s' from csmake environment", self.taggedEnvKey)
            del self.env.env[self.taggedEnvKey]
        except Exception as e:
            self.log.info("'%s' could not be removed from environment", self.taggedEnvKey)
            self.log.info("   Exception was: %s: %s", e.__class__.__name__, str(e) )
        self._unregisterOnExitCallback("_onExit")


    def _mountSystemPaths(self, mountpath):
        procmountpath = os.path.join(
            mountpath,
            'proc' )
        if not os.path.exists(procmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', procmountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of procfs mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'proc', 'none', procmountpath ],
            stdout = self.log.out(),
            stderr = self.log.err() )
        if result != 0:
            self.log.error("Mount of procfs failed")
            self.log.failed()
            return False
        self.mountedDevices.append(procmountpath)

        devmountpath = os.path.join(
            mountpath,
            'dev' )
        if not os.path.exists(devmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', devmountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of dev mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '--bind', '/dev', devmountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of dev failed")
            self.log.failed()
            return False
        self.mountedDevices.append(devmountpath)

        ptsmountpath = os.path.join(
            mountpath,
            'dev',
            'pts' )
        if not os.path.exists(ptsmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', ptsmountpath ],
                stdout=self.log.out(),
                stderr=self.log.err() )
            if result != 0:
                self.log.error("Create of the pts mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '--bind', '/dev/pts', ptsmountpath],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of dev/pts failed")
            self.log.failed()
            return False
        self.mountedDevices.append(ptsmountpath)

        sysmountpath = os.path.join(
            mountpath,
            'sys' )
        if not os.path.exists(sysmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', sysmountpath],
                stdout=self.log.out(),
                stderr=self.log.err() )
            if result != 0:
                self.log.error("Create of the sys mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'sysfs', 'none', sysmountpath],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of sysfs failed")
            self.log.failed()
            return False
        self.mountedDevices.append(sysmountpath)
        return True

    def _initModule(self):
        self.taggedEnvKey = self.ENVKEY
        if 'tag' in self.options:
            self.taggedEnvKey += self.options['tag']

        self.systemPartition = None
        self.partitionMapping = {}
        self.wholeDisk = False
        self.loopbackDevice = None
        self.mountMapping = {}
        self.mountedDevices = []

        #This will make mounting reenterant
        if self.taggedEnvKey in self.env.env:
            self.env.env[self.taggedEnvKey]['count'] += 1
            self.log.info("Mount called while already mounted - count now: %d", self.env.env[self.taggedEnvKey]['count'])
            self.log.passed()
            return False
        return True


    def _mount(self):
        self.wholeDisk = 'whole-disk' in self.options and self.options['whole-disk'] == 'True'
        #Ensure mount directory exists.
        if not os.path.exists(self.options['mounts']):
            subprocess.check_call(
                ['mkdir', '-p', self.options['mounts'] ],
                stdout=self.log.out(),
                stderr=self.log.err() )
        else:
            if not os.path.isdir(self.options['mounts']):
                self.log.error("'mounts' path '%s' already exists and is not a directory", self.options['mounts'])

        success = False
        try:
            p = subprocess.Popen(
                ['sudo', 'losetup', '--show', '-f', self.options['drive'] ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE )
            pout, perr = p.communicate()
            if p.returncode != 0:
                self.log.error("Creating loopback device for image failed")
                self.log.error(perr)
                self.log.failed()
                return False
            self.loopbackDevice = pout.strip()
            self.log.debug("Loopback device created: %s", self.loopbackDevice)

            if self.wholeDisk:
                self.mountMapping[''] = ''
            else:
                #Get the label/device mappings
                p = subprocess.Popen(
                    ['lsblk', '-P', '-i', '-o', 'name,label',
                        self.loopbackDevice],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE )
                pout, perr = p.communicate()
                if p.returncode != 0:
                    self.log.error("Could not get partition listing")
                    self.log.error(perr)
                    self.log.failed()
                    return False
                #Get the key/value pairs
                pairings = []
                lines = pout.split('\n')
                self.log.devdebug("Lines from lsblk: %s", str(lines))
                for line in lines:
                    if len(line.strip()) == 0:
                        continue
                    pairing = {}
                    pairings.append(pairing)
                    parts = line.split(' ')
                    self.log.devdebug("line parts: %s", str(parts))
                    for part in parts:
                        pair = part.split('=')
                        pairing[pair[0]] = pair[1].strip('"')
                    self.log.devdebug("Added paring: %s", str(pairing))
                #Older versions of lsblk do not have the -p option
                #This works around the issue.
                for pairing in pairings:
                    pairing['NAME'] = os.path.join('/dev', pairing['NAME'])
                for pairing in pairings:
                    name = pairing['NAME'][len(self.loopbackDevice):]
                    if len(name) == 0:
                        #This is the device, skip it
                        continue
                    label = pairing['LABEL']
                    if len(label) == 0:
                        #Older versions of lsblk don't properly retrieve the
                        #label.  Before giving up entirely, attempt to e2label
                        #the partition.
                        p = subprocess.Popen(
                            ['sudo', 'e2label', pairing['NAME']],
                            stdout = subprocess.PIPE,
                            stderr = subprocess.PIPE )
                        pout, perr = p.communicate()
                        gotLabel = False
                        if p.returncode != 0:
                            self.log.warning("Could not get a partition label for %s", pairing['NAME'])
                            self.log.warning(perr)
                        else:
                            label = pout.strip()
                            gotLabel = len(label) != 0
                            if gotLabel:
                                self.log.info("Got label '%s' for device '%s'", pairing['NAME'], label)
                                pairing['LABEL'] = label
                        if not gotLabel:
                            label = name
                    self.mountMapping[name] = label
                self.log.debug("Parings from lsblk: %s", str(self.mountMapping))
                if len(self.mountMapping.keys()) == 0:
                    self.log.error("The provided disk drive file '%s' had no partitions", self.options['drive'] )
                    self.log.error("   This module only works with partitioned drives")
                    self.log.failed()
                    return False

            #Mount volumes.
            systemLabel = None
            if 'system-label' in self.options:
                if self.wholeDisk:
                    self.log.error("Mounting a whole disk as a system disk is not supported")
                    self.log.failed()
                    return False
                systemLabel = self.options['system-label']
            systemLabelFound = False
            self.partitionMapping = {}
            for key, value in self.mountMapping.iteritems():
                device = self.loopbackDevice + key
                mountpath = os.path.join(
                    self.options['mounts'],
                    value )
                subprocess.check_call(
                    ['mkdir', '-p', mountpath],
                    stdout=self.log.out(),
                    stderr=self.log.err())
                result = subprocess.call(
                    ['sudo', 'mount', device, mountpath],
                    stdout=self.log.out(),
                    stderr=self.log.err() )
                if result != 0:
                    self.log.error("Mount failed")
                    self.log.failed()
                    return False
                self.partitionMapping[mountpath] = device
                self.mountedDevices.append(mountpath)
                if systemLabel == value:
                    if not self._mountSystemPaths(mountpath):
                        return False
                    systemLabelFound = True
                    self.systemPartition = (mountpath, device)
            if not systemLabelFound and systemLabel is not None:
                self.log.warning("The system label specified '%s' was not found", systemLabel)

            success = True
        except Exception as e:
            self.log.exception("Failed to mount disk")
            raise e
        finally:
            if not success:
                self._cleanUpMounts(True)
                return False

        #Create the mount record.
        self.env.env[self.taggedEnvKey] = {
            'count' : 1,
            'instance' : self,
            'device' : self.loopbackDevice,
            'partitions' : self.partitionMapping,
            'system-partition' : self.systemPartition }
        self._registerOnExitCallback("_onExit")
        return True

    def build(self, options):
        self.options = options
        if not self._initModule():
            self.log.passed()
            return
        if self._mount():
            self.log.passed()
        else:
            self.log.failed()

    def start__build(self, phase, options, step, stepoptions):
        self.options = options
        if not self._initModule():
            self.log.passed()
            return
        if self._mount():
            self.log.passed()
        else:
            self.log.failed()

    def end__build(self, phase, options, step, stepoptions):
        self._cleanUpMounts()
        self.log.passed()
