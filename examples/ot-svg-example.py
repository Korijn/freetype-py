#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  OT-SVG example
#
#  Copyright 2023 Hin-Tak Leung
#  Distributed under the terms of the new BSD license.

# This is largely a python re-write of freetype2-demos:src/rsvg-port.c .
#
# Limitation: it is necessary to have "_state" as a module-level global
# partially (in svg_init/svg_free, not in svg_render/svg_preset_slot)
# to stop python destroying it when execution is in the c-side.

import gi
gi.require_version('Rsvg', '2.0')

from gi.repository import Rsvg as rsvg

from freetype import *
from cairo import * # cairo.Matrix shadows freetype.Matrix

from math import ceil

_state = None

def svg_init(ctx):
    global _state
    _state = {}
    ctx.contents.value = _state
    return FT_Err_Ok

def svg_free(ctx):
    global _state
    _state = None
    # "None" is strictly speaking a special pyobject,
    # this line does not do what it should, i.e. setting the
    # pointer to NULL.
    ctx.contents = None
    return # void

def svg_render(slot, ctx):
    state = ctx.contents.value
    #pythonapi is imported from ctypes
    pythonapi.PyMemoryView_FromMemory.argtypes = (c_char_p, c_ssize_t, c_int)
    pythonapi.PyMemoryView_FromMemory.restype = py_object
    surface = ImageSurface.create_for_data( pythonapi.PyMemoryView_FromMemory(cast(slot.contents.bitmap.buffer, c_char_p),
                                                                              slot.contents.bitmap.rows * slot.contents.bitmap.pitch, 0x200),
                                            FORMAT_ARGB32,
                                            slot.contents.bitmap.width,
                                            slot.contents.bitmap.rows,
                                            slot.contents.bitmap.pitch )
    cr     = Context( surface )
    cr.translate( -state['x'], -state['y'] )

    cr.set_source_surface( state['rec_surface'] ) # 0,0 is default
    cr.paint()

    surface.flush()

    slot.contents.bitmap.pixel_mode = FT_PIXEL_MODE_BGRA
    slot.contents.bitmap.num_grays  = 256
    slot.contents.format            = FT_GLYPH_FORMAT_BITMAP

    return FT_Err_Ok

def svg_preset_slot(slot, cached, ctx):
    state = ctx.contents.value

    document = ctypes.cast(slot.contents.other, FT_SVG_Document)

    metrics        = SizeMetrics(document.contents.metrics)

    units_per_EM   = FT_UShort(document.contents.units_per_EM)
    end_glyph_id   = FT_UShort(document.contents.end_glyph_id)
    start_glyph_id = FT_UShort(document.contents.start_glyph_id)

    dimension_svg = rsvg.DimensionData()

    handle = rsvg.Handle.new_from_data( ctypes.string_at(document.contents.svg_document, # not terminated
                                                         size=document.contents.svg_document_length)
                                       )

    (out_has_width, out_width,
     out_has_height, out_height,
     out_has_viewbox, out_viewbox) = handle.get_intrinsic_dimensions()

    if ( out_has_viewbox == True ):
        dimension_svg.width  = out_viewbox.width
        dimension_svg.height = out_viewbox.height
    else:
        # "out_has_width" and "out_has_height" are True always
        dimension_svg.width  = units_per_EM;
        dimension_svg.height = units_per_EM;

        if (( out_width.length  != 1) or (out_height.length != 1 )):
            dimension_svg.width  = out_width.length
            dimension_svg.height = out_height.length

    x_svg_to_out = metrics.x_ppem / dimension_svg.width;
    y_svg_to_out = metrics.y_ppem / dimension_svg.height;

    state['rec_surface'] = RecordingSurface( Content.COLOR_ALPHA, None )

    rec_cr = Context( state['rec_surface'] )

    xx =  document.contents.transform.xx / ( 1 << 16 )
    xy = -document.contents.transform.xy / ( 1 << 16 )
    yx = -document.contents.transform.yx / ( 1 << 16 )
    yy =  document.contents.transform.yy / ( 1 << 16 )

    x0 =  document.contents.delta.x / 64 * dimension_svg.width / metrics.x_ppem
    y0 = -document.contents.delta.y / 64 * dimension_svg.height / metrics.y_ppem;

    transform_matrix = Matrix(xx, yx, xy, yy, x0, y0) # cairo.Matrix

    rec_cr.scale( x_svg_to_out, y_svg_to_out )

    rec_cr.transform( transform_matrix )

    viewport = rsvg.Rectangle()
    viewport.x = 0
    viewport.y = 0
    viewport.width = dimension_svg.width
    viewport.height = dimension_svg.height

    str = None # render whole document - not using Handle.render_document()
    if ( start_glyph_id.value < end_glyph_id.value ):
        str = "#glyph%u" % (slot.contents.glyph_index )

    handle.render_layer( rec_cr, str, viewport )

    (state['x'], state['y'], width, height) = state['rec_surface'].ink_extents()

    slot.contents.bitmap_left = int(state['x'])
    slot.contents.bitmap_top  = int(-state['y'])

    slot.contents.bitmap.rows  = ceil( height )
    slot.contents.bitmap.width = ceil( width )

    slot.contents.bitmap.pitch = slot.contents.bitmap.width * 4

    slot.contents.bitmap.pixel_mode = FT_PIXEL_MODE_BGRA

    metrics_width  = width;
    metrics_height = height;

    horiBearingX =  state['x']
    horiBearingY = -state['y']

    vertBearingX = slot.contents.metrics.horiBearingX / 64.0 - slot.contents.metrics.horiAdvance / 64.0 / 2
    vertBearingY = ( slot.contents.metrics.vertAdvance / 64.0 - slot.contents.metrics.height / 64.0 ) / 2

    slot.contents.metrics.width  = int(round( metrics_width * 64 ))
    slot.contents.metrics.height = int(round( metrics_height * 64 ))

    slot.contents.metrics.horiBearingX = int( horiBearingX * 64 )
    slot.contents.metrics.horiBearingY = int( horiBearingY * 64 )
    slot.contents.metrics.vertBearingX = int( vertBearingX * 64 )
    slot.contents.metrics.vertBearingY = int( vertBearingY * 64 )

    if ( slot.contents.metrics.vertAdvance == 0 ):
        slot.contents.metrics.vertAdvance = int( metrics_height * 1.2 * 64 )

    if ( cached == False ):
        state['rec_surface'] = None
        state['x'] = 0
        state['y'] = 0

    return FT_Err_Ok

hooks = SVG_RendererHooks(svg_init=SVG_Lib_Init_Func(svg_init),
                          svg_free=SVG_Lib_Free_Func(svg_free),
                          svg_render=SVG_Lib_Render_Func(svg_render),
                          svg_preset_slot=SVG_Lib_Preset_Slot_Func(svg_preset_slot))

if __name__ == '__main__':
    import sys
    import numpy as np
    execname = sys.argv[0]

    if len(sys.argv) < 2:
        print("Example usage: %s TrajanColor-Concept.otf" % execname)
        exit(1)

    face = Face(sys.argv[1])

    face.set_char_size( 160*64 )
    library = get_handle()
    FT_Property_Set( library, b"ot-svg", b"svg-hooks", byref(hooks) ) # python 3 only syntax
    face.load_char('A', FT_LOAD_COLOR | FT_LOAD_RENDER )

    bitmap = face.glyph.bitmap
    width = face.glyph.bitmap.width
    rows = face.glyph.bitmap.rows

    if ( face.glyph.bitmap.pitch != width * 4 ):
        raise RuntimeError('pitch != width * 4 for color bitmap: Please report this.')
    bitmap = np.array(bitmap.buffer, dtype=np.uint8).reshape((bitmap.rows,bitmap.width,4))

    I = ImageSurface(FORMAT_ARGB32, width, rows)
    try:
        ndI = np.ndarray(shape=(rows,width), buffer=I.get_data(),
                         dtype=np.uint32, order='C',
                         strides=[I.get_stride(), 4])
    except NotImplementedError:
        raise SystemExit("For python 3.x, you need pycairo >= 1.11+ (from https://github.com/pygobject/pycairo)")

    ndI[:,:] = bitmap[:,:,3] * 2**24 + bitmap[:,:,2] * 2**16 + bitmap[:,:,1] * 2**8 + bitmap[:,:,0]

    I.mark_dirty()

    surface = ImageSurface(FORMAT_ARGB32, 2*width, rows)
    ctx = Context(surface)

    ctx.set_source_surface(I, 0, 0)
    ctx.paint()

    ctx.set_source_surface(I, width/2, 0)
    ctx.paint()

    ctx.set_source_surface(I, width , 0)
    ctx.paint()

    surface.write_to_png("ot-svg-example.png")

    from PIL import Image
    Image.open("ot-svg-example.png").show()
