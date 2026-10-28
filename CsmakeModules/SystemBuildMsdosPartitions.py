# <copyright>
# (c) Copyright 2019 Autumn Samantha Jeremiah Pattersosn
# (c) Copyright 2018 Cardinal Peak Technologies
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
from CsmakeCore.CsmakeModule import CsmakeModule
import subprocess
import re

class SystemBuildMsdosPartitions(CsmakeModule):
    """Purpose: Set up partitions on a disk for a system build.
       Library: csmake-system-build
       Phases: build, system_build - create the file and definition
           use_system_build - reuse the created partitions
       Options:
           system - Name of the system to add partitions to
           disk-name - Name of the disk to partition
           part_<partition> - Definition of partition
               The fields for the entries are:
                   <order>, <size>, <type>[, <flags>]
                   order - position on the disk
                           This is sorted in lexicigraphical order
                           If you have more than 9 partitions, use
                           01, 02, 03, ..., 10, 11, 12 to create the
                           partitions.
                           These labels do not dictate the actual partition
                           numbers.  The partitions will be labeled
                           in order based on how the partitioning scheme
                           works.
                           (use '<ex>E' for an extended partition
                            msdos tables only allow 4 primary/extended
                            partitions)
                           (start with '<ex>E:<logical>L' for a partition
                            within the extended partition
                           (the logical partition numbering for logical
                            partitions will start at 5 on the system regardless
                            of the numbers used for 'order')
                   size - Size of the partition in G or M
                          Sizes are suggestions with size being within
                          1% of the size of the disk and optimazations
                   type - number or hex number (e.g., 0x84)
                          or a defined type (e.g., Linux)
                          defined types are (per parted):
                              ext2 - a linux partition
                              linux - a linux partition
                              linux-swap - linux swap partition
                              fat16 - an old windows partition
                              vfat, fat32 - a vfat windows partition
                              HFS - an HFS parition
                              NTFS - an NTFS partition

                   flags - (optional) If the partition is bootable,
                          add "boot" to the end, for example.
                          0 to n flags may be specified.
                          flags are based on parted's flags:
                          boot - bootable partition
                          root - the root file system partition
                          swap - a swap partition
                          hidden - a hidden parittion
                          raid - a raidable partition
                          lvm - an lvm partition
                          lba - use logical block addressing
                          legacy_boot - a legacy boot parition (non-UEFI)
                          palo - ???
       Notes:
           - Partitions will be top to bottom, no gaps
             A special module would be required to enable
             adding partitions to the bottom of the disk space
           - The first partition starts on sector 2048, which is compatible
             with the most schemes.
       Environment:
           __SystemBuild_<system>__ is referenced - it is an error
              to not have the referenced system defined
              a 'disks' entry is expected to exist with th referenced disk
              i.e., SystemBuildDisk section defining the disk has already
                    been executed.
              This will update the entry with the partition table of the disk
              as 'partitions', which will be a dictionary with the partition
              name as the key from part_<name> of:
                 number - the parittion number
                 size - the size of the partition
                 device - the full device (current device)
                 fstab-id - the fstab-id to use, e.g. LABEL="blah"
              also a 'swaps' entry will be added to the disk's dictionary
                 this will list the access information for any swap partitions
                 the structure of swaps is [(label, partition dictionary)...]
       Requires: parted and sfdisk
    """

    REQUIRED_OPTIONS = ['system', 'disk-name']

    PART_FSTYPES = {
        'ext2' : 'ext2',
        'linux' : 'ext2',
        'fat16' : 'fat16',
        'fat32' : 'fat32',
        'vfat' : 'fat32',
        'HFS' : 'HFS',
        'NTFS' : 'NTFS',
        'linux-swap' : 'linux-swap',
        'reiserfs' : 'reiserfs',
        'ufs' : 'ufs' }

    PART_TYPE = "msdos"
    PART_PRIMARY_PARTITIONS = 4
    PART_LOGICAL_EXTENDED_ALLOWED = True
    #Tell parted to start on sector 2048
    PART_FIRST_START = "2048s"

    def _getEnvKey(self, system):
        return "__SystemBuild_%s__" % system

    def _getRequestedPercentage(self, size):
        requestedSize = self.systemInstance._getSizeInBytes(size)
        result = int(round(requestedSize*100.0/self.disksize))
        if result == 0:
            result = 1
            self.log.warning("The requested partition was too small (%s), the partition has been rounded up to the next available size", size)
        return result

    def _editPartitionWithSfdisk(self, device, number, partition):
        result = subprocess.call(
            ['sudo', 'sfdisk', '--part-type', device, "%d" % number, partition[3]],
            stdout = self.log.out(),
            stderr = self.log.err() )
        if result != 0:
            self.log.warning("Did not successfully set the requested partition type")
        
    #Structure of the partition is name, order, size, type, flag(boot)
    def _createNextPartition(
        self, device, number, parttype, partition, start, end):
        fstype='ext2'
        callsfdisk = False
        if parttype == 'extended':
            command_specifics = []
        else:
            if partition[3] in self.PART_FSTYPES:
                fstype = self.PART_FSTYPES[partition[3]]
            else:
                callsfdisk = True
            command_specifics = [ fstype ]
        if start == 0:
            startstr = self.PART_FIRST_START
        else:
            startstr = "%s%%" % start
        subprocess.check_call(
            ['sudo', 'parted', '-s', '-a', 'optimal', device, '--',
              'mkpart', parttype] + command_specifics + [startstr, "%d%%" % end],
            stdout=self.log.out(),
            stderr=self.log.err() )
        subprocess.call(
            ['sudo', 'parted', '-s', device, '--', 'name', '%d' % number, partition[0]],
            stdout = self.log.out(),
            stderr = self.log.err())
        if len(partition) > 4:
            for flag in partition[4:]:
                subprocess.check_call(
                    ['sudo', 'parted', '-s', device, '--',
                     'set', "%d" % number, flag, 'on'],
                    stdout = self.log.out(),
                    stderr = self.log.err())
        if callsfdisk:
            self._editPartitionWithSfdisk(device, number, partition)
        if fstype == 'linux-swap':
            self.swaps.append((device, number, partition))

    def _createPrimaryPartition(self, device, number, partition):
        requestedPercent = self._getRequestedPercentage(partition[2])
        start = self.startPercent
        end = start + requestedPercent
        if end > 100:
            self.log.warning("Primary partition was truncated, %d%% beyond the end of the disk", end-100)
            end = 100
        self._createNextPartition(
            device, number, 'primary', partition, start, end)
        self.startPercent = end

    def _createExtendedPartition(self, device, number, partition):
        requestedPercent = self._getRequestedPercentage(partition[2])
        start = self.startPercent
        end = start + requestedPercent
        if end > 100:
            self.log.warning("Extended partition was truncated, %d%% beyond the end of the disk", 100-end)
            end = 100
        self._createNextPartition(
            device, number, 'extended', partition, start, end)
        self.extensionStart = start
        self.extensionEnd = end

    def _createLogicalPartition(self, device, number, partition):
        if self.extensionStart == -1:
            self.log.error("Creating a logical partition without an extended partition")
            raise SystemError("Logical partitions require extended partitions")
        requestedPercent = self._getRequestedPercentage(partition[2])
        start = self.extensionStart
        end = start + requestedPercent
        if end > self.extensionEnd:
            self.log.warning("Logical partition was truncated, %d%% beyond the extended partition", self.extensionEnd - end)
            end = self.extensionEnd
        self._createNextPartition(
            device, number, 'logical', partition, start, end)
        self.extensionStart = end

    def _createPartitionEntry(self, part, number, device, diskFstabId, partFstabId=None):
        fulldevstring = device
        fullpartid = diskFstabId
        if number > 0:
            partsep = ''
            if 'loop' in device:
                partsep = 'p'
            fulldevstring = "%s%s%d" % (device, partsep, number)
            partsep = ''
            if 'loop' in diskFstabId:
                partsep = 'p'
            fullpartid = "%s%s%d" % (diskFstabId, partsep, number)
        if partFstabId is None:
            if '=' not in diskFstabId:
                partFstabId = fullpartid
            #TODO: What if the disk has an identifier, but nothing for the
            #      partition - then what???
        self.partEntry[part[0]] = {
            'number' : number,
            'size' : part[2],
            'device' : fulldevstring,
            'fstab-id' : partFstabId }

    def system_build(self, options):
        return self.build(options)
    def build(self, options):
        return self._doPartitioning(options, True)
    def use_system_build(self, options):
        return self._doPartitioning(options, False)

    def _doPartitioning(self, options, build):
        self.swaps = []
        system = options['system']
        diskname = options['disk-name']
        key = self._getEnvKey(system)
        if key not in self.env.env:
            self.log.error("System '%s' is not defined", system)
            self.log.failed()
            return None
        systemEntry = self.env.env[key]
        if 'disks' not in systemEntry or diskname not in systemEntry['disks']:
            self.log.error("Disk '%s' is not defined for system '%s'", diskname, system)
            self.log.failed()
            return None
        diskEntry = systemEntry['disks'][diskname]
        if 'partitions' in diskEntry:
            self.log.error("Parititions have already been defined for disk '%s'", diskname)
            self.log.failed()
            return None
        diskEntry['partitions'] = {}
        diskEntry['swaps'] = []
        self.partEntry = diskEntry['partitions']
        partitions=[]
        if build:
            subprocess.check_call(
                ['sudo', 'parted', '-s', diskEntry['device'], '--', 'mklabel', self.PART_TYPE],
                stdout=self.log.out(),
                stderr=self.log.err())

        #Get the sizes ready for creating partitions
        self.systemInstance = systemEntry['system']
        #parted on ubuntu14.04 is stupid...starting at 0 causes it to make a 1M
        #  partition...so what we do is start it at sector 2048
        self.startPercent = 0
        self.disksize = diskEntry['size']
        self.extensionStart = -1
        self.extensionEnd= -1

        for key, value in options.items():
            if key.startswith('part_'):
                name = key[5:]
                partition = [name]
                partition.extend(value.split(','))
                partition = [ x.strip() for x in partition if len(x.strip()) > 0 ]
                partitions.append( partition )
        self.log.devdebug("Processing partitions: %s", partitions)
        partitions.sort(key=lambda x: x[1])
        #NOTE: assuming and assigning part numbers based on p/e/l volume
        #      creation ordering in parted.
        #Consider that the partition number assumption could be checked
        #  by showing that the parition number did not exist, and then
        #  after creating the partition, it does exist.
        primary = 1
        extended = ""
        logical = 5
        for part in partitions:
            try:
                if part[1][-1] == 'L':
                    if not self.PART_LOGICAL_EXTENDED_ALLOWED:
                        self.log.error("Logical volumes are not allowed with type '%s'", self.PART_TYPE)
                        self.log.failed()
                        return None
                    if len(part[1]) < 4 or part[1][1] != 'E' or part[1][2] != ':':
                        self.log.error("The format of 'part_%s' option is incorrect", part[0])
                        self.log.error("   got: %s", part[1])
                        self.log.error("   format required: <ex>:<part>L")
                        self.log.error("      e.g.: 2:5L  where 2 is an extended partition")
                        self.log.failed()
                        return None
                    if build:
                        self._createLogicalPartition(
                            diskEntry['device'],
                            logical,
                            part )
                    self._createPartitionEntry(
                        part,
                        logical,
                        diskEntry['device'],
                        diskEntry['fstab-id'])
                    logical += 1

                elif part[1][-1] == 'E':
                    if not self.PART_LOGICAL_EXTENDED_ALLOWED:
                        self.log.error("Logical volumes are not allowed with type '%s'", self.PART_TYPE)
                        self.log.failed()
                        return None
                    if primary > self.PART_PRIMARY_PARTITIONS:
                        self.log.error("%s partition tables may only have 4 primary and extended partitions", self.PART_TYPE)
                        self.log.error("   However, part_%s defines a 5th partition", part[0])
                        self.log.failed()
                        return None
                    if len(part[1]) < 2:
                        self.log.error("The format of 'part_%s' option is incorrect", part[0])
                        self.log.error("    got: %s", part[1])
                        self.log.error("    format required: <ex>E")
                        self.log.error("       e.g.: 3E")
                        self.log.failed()
                        return None
                    if self.extensionStart != -1:
                        self.log.error("The disk can only have one extended partition")
                        self.log.error("   part_%s specified a second extended partition", part[0] )
                        self.log.failed()
                        return None
                    if build:
                        self._createExtendedPartition(
                            diskEntry['device'],
                            primary,
                            part )
                    self._createPartitionEntry(
                        part,
                        primary,
                        diskEntry['device'],
                        diskEntry['fstab-id'])
                    extension = str(primary)
                    primary += 1

                else:
                    if primary > self.PART_PRIMARY_PARTITIONS:
                        self.log.error("%s partition tables may only have 4 primary and extended sections", self.PART_TYPE)
                        self.log.error("   However, part_%s defines a 5th partition", part[0])
                        self.log.failed()
                        return None
                    if build:
                        self._createPrimaryPartition(
                            diskEntry['device'],
                            primary,
                            part )
                    self._createPartitionEntry(
                        part,
                        primary,
                        diskEntry['device'],
                        diskEntry['fstab-id'])
                    primary += 1
            except ValueError as v:
                self.log.exception('Partition "%s" creation failed', part)
                self.log.failed()
                return None
            except subprocess.CalledProcessError as cpe:
                self.log.exception('Partition "%s" shell call failed', part)
                self.log.failed()
                return None
        result = subprocess.call(
            ['sudo', 'partprobe', diskEntry['device']],
            stdout=self.log.out(),
            stderr=self.log.err())
        if result != 0:
            self.log.warning("Part probe failed")
        result = subprocess.call(
            ['sudo', 'udevadm', 'settle'],
            stdout=self.log.out(),
            stderr=self.log.err())
        if result != 0:
            self.log.warning("settle failed")
        for partdev, partnum, partpartition in self.swaps:
            try:
                if build:
                    subprocess.check_call(
                        ['sudo', 'mkswap', '-L',
                           partpartition[0],
                           self.partEntry[partpartition[0]]['device']],
                        stdout=self.log.out(),
                        stderr=self.log.err())
                self.partEntry[partpartition[0]]['fstab-id'] = 'LABEL=%s' % partpartition[0]
                diskEntry['swaps'].append((partpartition[0], self.partEntry[partpartition[0]]))
            except:
                self.log.exception("The swap, '%s', could not be initialized", partpartition[0])

        self.log.passed()
        return self.partEntry
