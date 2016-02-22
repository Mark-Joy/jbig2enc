#!/usr/bin/python
# Copyright 2006 Google Inc.
# Author: agl@imperialviolet.org (Adam Langley)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# JBIG2 Encoder
# https://github.com/agl/jbig2enc

import sys
import re
import struct
import glob
import os

# This is a very simple script to make a PDF file out of the output of a
# multipage symbol compression.
# Run ./jbig2 -s -p <other options> image1.jpeg image1.jpeg ...
# python pdf.py output > out.pdf

class Ref:
  def __init__(self, x):
    self.x = x
  def __str__(self):
    return "%d 0 R" % self.x

class Dict:
  def __init__(self, values = {}):
    self.d = {}
    self.d.update(values)

  def __str__(self):
    s = ['<< ']
    for (x, y) in self.d.items():
      s.append('/%s ' % x)
      s.append(str(y))
      s.append("\n")
    s.append(">>\n")

    return ''.join(s)

global_next_id = 1

class Obj:
  next_id = 1
  def __init__(self, d = {}, stream = None):
    global global_next_id

    if stream is not None:
      d['Length'] = str(len(stream))
    self.d = Dict(d)
    self.stream = stream
    self.id = global_next_id
    global_next_id += 1

  def __str__(self):
    s = []
    s.append(str(self.d))
    if self.stream is not None:
      s.append('stream\n')
      s.append(self.stream)
      s.append('\nendstream\n')
    s.append('endobj\n')

    return ''.join(s)

class Doc:
  def __init__(self):
    self.objs = []
    self.pages = []

  def add_object(self, o):
    self.objs.append(o)
    return o

  def add_page(self, o):
    self.pages.append(o)
    return self.add_object(o)

  def __str__(self):
    a = []
    j = [0]
    offsets = []

    def add(x):
      a.append(x)
      j[0] += len(x) + 1
    add('%PDF-1.4')
    for o in self.objs:
      offsets.append(j[0])
      add('%d 0 obj' % o.id)
      add(str(o))
    xrefstart = j[0]
    a.append('xref')
    a.append('0 %d' % (len(offsets) + 1))
    a.append('0000000000 65535 f ')
    for o in offsets:
      a.append('%010d 00000 n ' % o)
    a.append('')
    a.append('trailer')
    a.append('<< /Size %d\n/Root 1 0 R >>' % (len(offsets) + 1))
    a.append('startxref')
    a.append(str(xrefstart))
    a.append('%%EOF')

    # sys.stderr.write(str(offsets) + "\n")

    return '\n'.join(a)

def ref(x):
  return '%d 0 R' % x

# https://www.opennet.ru/docs/formats/jpeg.txt
#
# - $ff, $c0 (SOF0)
# - length (high byte, low byte), 8+components*3
# - data precision (1 byte) in bits/sample, usually 8 (12 and 16 not
#   supported by most software)
# - image height (2 bytes, Hi-Lo), must be >0 if DNL not supported
# - image width (2 bytes, Hi-Lo), must be >0 if DNL not supported
# - number of components (1 byte), usually 1 = grey scaled, 3 = color YCbCr
#   or YIQ, 4 = color CMYK)
# - for each component: 3 bytes
#    - component id (1 = Y, 2 = Cb, 3 = Cr, 4 = I, 5 = Q)
#    - sampling factors (bit 0-3 vert., 4-7 hor.)
#    - quantization table number

def loadimage(contents, symd):
  if contents[6:10] == "JFIF":
    pos = 0
    pos += 2
    b = contents[pos]
    while (b and ord(b) != 0xDA):
        while (ord(b) != 0xFF):
          b = contents[pos]
          pos = pos + 1
        while (ord(b) == 0xFF):
          b = contents[pos]
          pos = pos + 1
        if (ord(b) >= 0xC0 and ord(b) <= 0xC3):
            pos += 2
            comps = ord(contents[pos])
            pos += 1
            h, w = struct.unpack(">HH", contents[pos:pos+4])
            pos += 4
            t = ord(contents[pos])
            break
        else:
            s = int(struct.unpack(">H", contents[pos:pos+2])[0])-2
            pos += s
        b = contents[pos]
        pos = pos + 1

    width = int(w)
    height = int(h)

    dens = contents[0x0d]
    if ord(dens) != 0x01: # Pixels per inch (2.54 cm)
      raise "wrong dens"
    xres, yres = struct.unpack(">HH", contents[0x0e:0x12])
    
    if t == 0x01:
      tt = "/DeviceGray"
    if t == 0x03:
      tt = "/DeviceRGB"

    # sys.stderr.write("JP: %d %s %d %d %s %d %d\n" % (comps, tt, width, height, str(len(contents)), xres, yres))
    
    if xres == 0:
        xres = 150
    if yres == 0:
        yres = 150

    xobj = Obj({'Type': '/XObject', 'Subtype': '/Image',
        'Width': str(width),
        'Height': str(height),
        'ColorSpace': tt,
        'BitsPerComponent': str(comps),
        'Length': str(len(contents)),
        'Filter': '/DCTDecode'}, contents)

    return (width, height, xres, yres, xobj)
  else:
    (width, height, xres, yres) = struct.unpack('>IIII', contents[11:27])

    if xres == 0:
        xres = 300
    if yres == 0:
        yres = 300

    xobj = Obj({'Type': '/XObject', 'Subtype': '/Image', 'Width':
        str(width), 'Height': str(height), 'ColorSpace': '/DeviceGray',
        'BitsPerComponent': '1', 'Filter': '/JBIG2Decode', 'DecodeParms':
        ' << /JBIG2Globals %d 0 R >>' % symd.id}, contents)

    return (width, height, xres, yres, xobj)

def main(symboltable='symboltable', pagefiles=glob.glob('page-*')):
  doc = Doc()
  doc.add_object(Obj({'Type' : '/Catalog', 'Outlines' : ref(2), 'Pages' : ref(3)}))
  doc.add_object(Obj({'Type' : '/Outlines', 'Count': '0'}))
  pages = Obj({'Type' : '/Pages'})
  doc.add_object(pages)
  symd = doc.add_object(Obj({}, file(symboltable, 'rb').read()))
  page_objs = []

  for p in pagefiles:
    p = p.strip()
    try:
      contents = file(p, mode='rb').read()
    except IOError:
      sys.stderr.write("error reading page file %s\n"% p)
      continue
      
    (width, height, xres, yres, xobj) = loadimage(contents, symd)

    contents = Obj({}, 'q %f 0 0 %f 0 0 cm /Im1 Do Q' % (float(width * 72) / xres, float(height * 72) / yres))
    resources = Obj({'ProcSet': '[/PDF /ImageB]',
        'XObject': '<< /Im1 %d 0 R >>' % xobj.id})
    page = Obj({'Type': '/Page', 'Parent': '3 0 R',
        'MediaBox': '[ 0 0 %f %f ]' % (float(width * 72) / xres, float(height * 72) / yres),
        'Contents': ref(contents.id),
        'Resources': ref(resources.id)})
    [doc.add_object(x) for x in [xobj, contents, resources, page]]
    page_objs.append(page)

    pages.d.d['Count'] = str(len(page_objs))
    pages.d.d['Kids'] = '[' + ' '.join([ref(x.id) for x in page_objs]) + ']'

  print str(doc)


def usage(script, msg):
  if msg:
    sys.stderr.write("%s: %s\n"% (script, msg))
  sys.stderr.write("Usage: %s [file_basename] > out.pdf\n"% script)
  sys.exit(1)

if __name__ == '__main__':
  if sys.platform == "win32":
    import msvcrt
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

  if len(sys.argv) == 2:
    if sys.argv[1] == "index":
      with open('index', 'r') as index:
        pages = index.readlines()
      sym = "J.sym"
    else:
      sym = sys.argv[1] + '.sym'
      pages = glob.glob(sys.argv[1] + '.[0-9]*')
      pages.sort()
  elif len(sys.argv) == 1:
    sym = 'symboltable'
    pages = glob.glob('page-*')
    pages.sort()
  else:
    usage(sys.argv[0], "wrong number of args!")

  if not os.path.exists(sym):
    usage(sys.argv[0], "symbol table %s not found!"% sym)
  elif len(pages) == 0:
    usage(sys.argv[0], "no pages found!")
    
  main(sym, pages)
