#!/usr/bin/python
#
#  shared.py - common functions, classes, and variables for Vcycle
#
#  Andrew McNab, University of Manchester.
#  Copyright (c) 2013-4. All rights reserved.
#
#  Redistribution and use in source and binary forms, with or
#  without modification, are permitted provided that the following
#  conditions are met:
#
#    o Redistributions of source code must retain the above
#      copyright notice, this list of conditions and the following
#      disclaimer. 
#    o Redistributions in binary form must reproduce the above
#      copyright notice, this list of conditions and the following
#      disclaimer in the documentation and/or other materials
#      provided with the distribution. 
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
#  CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
#  INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS
#  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
#  EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
#  TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
#  ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
#  OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.
#
#  Contacts: Andrew.McNab@cern.ch  http://www.gridpp.ac.uk/vcycle/
#

import os
import sys
import stat
import time
import string
import pycurl
import StringIO
import tempfile
import ConfigParser

import vcycle.vacutils

vcycleVersion = None
spaces        = None
lastFizzles   = {}

def readConf(requirePassword=True):

  global vcycleVersion, spaces, lastFizzles

  try:
    f = open('/var/lib/vcycle/VERSION', 'r')
    vcycleVersion = f.readline().split('=',1)[1].strip()
    f.close()
  except:
    vcycleVersion = '0.0.0'
  
  spaces = {}

  spaceStrOptions = [ 'tenancy_name', 'url', 'username' ]

  spaceIntOptions = [ 'max_machines' ]

  vmtypeStrOptions = [ 'image_name', 'flavor_name', 'root_key_name', 'x509dn' ]

  vmtypeIntOptions = [ 'max_machines', 'backoff_seconds', 'fizzle_seconds', 'max_wallclock_seconds' ]

  parser = ConfigParser.RawConfigParser()
  
  # Look for configuration files in /etc/vcycle.d
  try:
    confFiles = os.listdir('/etc/vcycle.d')
  except:
    pass 
  else:
    for oneFile in sorted(confFiles):
      if oneFile[-5:] == '.conf':      
        try:
          parser.read('/etc/vcycle.d/' + oneFile)
        except Exception as e:
          vcycle.vacutils.logLine('Failed to parse /etc/vcycle.d/' + oneFile + ' (' + str(e) + ')')

  # Standalone configuration file, read last in case of manual overrides
  parser.read('/etc/vcycle.conf')

  # First look for space sections

  for spaceSectionName in parser.sections():
    split1 = spaceSectionName.lower().split(None,1)

    if split1[0] == 'vmtype':    
      continue
      
    elif split1[0] != 'space':
      return 'Section type ' + split1[0] + ' not recognised'
      
    else:
      spaceName = split1[1]
      
      if string.translate(spaceName, None, '0123456789abcdefghijklmnopqrstuvwxyz-.') != '':
        return 'Name of space section [space ' + spaceName + '] can only contain a-z 0-9 - or .'
      
      space = {}
      
      # Get the options from this section for this space
        
      for opt in spaceStrOptions:
        if parser.has_option(spaceSectionName, opt):
          space[opt] = parser.get(spaceSectionName, opt)
        else:
          return 'Option ' + opt + ' required in [' + spaceSectionName + ']'

      for opt in spaceIntOptions:
        try:
          space[opt] = int(parser.get(spaceSectionName, opt))
        except:
          return 'Option ' + opt + ' required in [' + spaceSectionName + ']'

      try:
        # We use ROT-1 (A -> B etc) encoding so browsing around casually doesn't
        # reveal passwords in a memorable way. 
        space['password'] = ''.join([ chr(ord(c)-1) for c in parser.get(spaceSectionName, 'password')])
      except:
        if requirePassword:
          return 'Option password is required in [' + spaceSectionName + ']'
        else:
          space['password'] = ''

      try:
        space['delete_old_files'] = bool(parser.get(spaceSectionName, 'delete_old_files'))
      except:
        space['delete_old_files'] = True

      # Get the options for each vmtype section associated with this space

      vmtypes = {}

      for vmtypeSectionName in parser.sections():
        split2 = vmtypeSectionName.lower().split(None,2)

        if split2[0] == 'vmtype':

          if split2[1] == spaceName:
            vmtypeName = split2[2]

            if string.translate(vmtypeName, None, '0123456789abcdefghijklmnopqrstuvwxyz-') != '':
              return 'Name of vmtype section [vmtype ' + spaceName + ' ' + vmtypeName + '] can only contain a-z 0-9 or -'
      
            vmtype = {}

            for opt in vmtypeStrOptions:              
              if parser.has_option(vmtypeSectionName, opt):
                vmtype[opt] = parser.get(vmtypeSectionName, opt)
              else:
                return 'Option ' + opt + ' required in [' + vmtypeSectionName + ']'

            for opt in vmtypeIntOptions:
              try:
                vmtype[opt] = int(parser.get(vmtypeSectionName, opt))
              except:
                return 'Option ' + opt + ' required in [' + vmtypeSectionName + ']'

            try:
              vmtype['heartbeat_file'] = parser.get(vmtypeSectionName, 'heartbeat_file')
            except:
              pass

            try:
              vmtype['heartbeat_seconds'] = int(parser.get(vmtypeSectionName, 'heartbeat_seconds'))
            except:
              pass

            try:
              vmtype['user_data'] = parser.get(vmtypeSectionName, 'user_data')
            except:
              vmtype['user_data'] = 'user_data'

            for (oneOption,oneValue) in parser.items(vmtypeSectionName):
              if (oneOption[0:17] == 'user_data_option_') or (oneOption[0:15] == 'user_data_file_'):
                if string.translate(oneOption, None, '0123456789abcdefghijklmnopqrstuvwxyz_') != '':
                  return 'Name of user_data_xxx (' + oneOption + ') must only contain a-z 0-9 and _'
                else:
                  vmtype[oneOption] = parser.get(vmtypeSectionName, oneOption)

            try:
              vmtype['target_share'] = float(parser.get(vmtypeSectionName, 'target_share'))
            except:
              return 'Option target_share required in [' + vmtypeSectionName + ']'
            
            if parser.has_option(vmtypeSectionName, 'log_machineoutputs') and \
               parser.get(vmtypeSectionName, 'log_machineoutputs').strip().lower() == 'true':
              vmtype['log_machineoutputs'] = True
            else:
              vmtype['log_machineoutputs'] = False

            if parser.has_option(vmtypeSectionName, 'machineoutputs_days'):
              vmtype['machineoutputs_days'] = float(parser.get(vmtypeSectionName, 'machineoutputs_days'))
            else:
              vmtype['machineoutputs_days'] = 3.0

            if spaceName not in lastFizzles:
              lastFizzles[spaceName] = {}
              
            if vmtypeName not in lastFizzles[spaceName]:
              lastFizzles[spaceName][vmtypeName] = int(time.time()) - vmtype['backoff_seconds']

            vmtypes[vmtypeName] = vmtype

      if len(vmtypes) < 1:
        return 'No vmtypes defined for space ' + spaceName + ' - each space must have at least one vmtype'

      space['vmtypes']  = vmtypes
      spaces[spaceName] = space

  return None

#def createFile(targetname, contents, mode=None):
#  # Create a text file containing contents in the vcycle tmp directory
#  # then move it into place. Rename is an atomic operation in POSIX,
#  # including situations where targetname already exists.
#   
#  try:
#    ftup = tempfile.mkstemp(prefix='/var/lib/vcycle/tmp/temp',text=True)
#    os.write(ftup[0], contents)
#       
#    if mode: 
#      os.fchmod(ftup[0], mode)
#
#    os.close(ftup[0])
#    os.rename(ftup[1], targetname)
#    return True
#  except:
#    return False
#
#def logLine(text):
#  sys.stderr.write(time.strftime('%b %d %H:%M:%S [') + str(os.getpid()) + ']: ' + text + '\n')
#  sys.stderr.flush()

def logMachineoutputs(hostName, vmtypeName, spaceName):

  if os.path.exists('/var/lib/vcycle/machineoutputs/' + spaceName + '/' + vmtypeName + '/' + hostName):
    # Copy (presumably) already exists so don't need to do anything
    return
   
  try:
    os.makedirs('/var/lib/vcycle/machineoutputs/' + spaceName + '/' + vmtypeName + '/' + hostName,
                stat.S_IWUSR + stat.S_IXUSR + stat.S_IRUSR + stat.S_IXGRP + stat.S_IRGRP + stat.S_IXOTH + stat.S_IROTH)
  except:
    vcycle.vacutils.logLine('Failed creating /var/lib/vcycle/machineoutputs/' + spaceName + '/' + vmtypeName + '/' + hostName)
    return
      
  try:
    # Get the list of files that the VM wrote in its /etc/machineoutputs
    outputs = os.listdir('/var/lib/vcycle/machines/' + hostName + '/machineoutputs')
  except:
    vcycle.vacutils.logLine('Failed reading /var/lib/vcycle/machines/' + hostName + '/machineoutputs')
    return
        
  if outputs:
    # Go through the files one by one, adding them to the machineoutputs directory
    for oneOutput in outputs:

      try:
        # first we try a hard link, which is efficient in time and space used
        os.link('/var/lib/vcycle/machines/' + hostName + '/machineoutputs/' + oneOutput,
                '/var/lib/vcycle/machineoutputs/' + spaceName + '/' + vmtypeName + '/' + hostName + '/' + oneOutput)
      except:
        try:
          # if linking failed (different filesystems?) then we try a copy
          shutil.copyfile('/var/lib/vcycle/machines/' + hostName + '/machineoutputs/' + oneOutput,
                          '/var/lib/vcycle/machineoutputs/' + spaceName + '/' + vmtypeName + '/' + hostName + '/' + oneOutput)
        except:
          vcycle.vacutils.logLine('Failed copying /var/lib/vcycle/machines/' + hostName + '/machineoutputs/' + oneOutput + 
                  ' to /var/lib/vcycle/machineoutputs/' + spaceName + '/' + vmtypeName + '/' + hostName + '/' + oneOutput)

  