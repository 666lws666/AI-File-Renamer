"""Fixed public raster fixtures for explicit diagnostics; no external inputs."""
from __future__ import annotations

import io
from pathlib import Path


def _canvas():
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (960, 720), '#faf8f0')
    return image, ImageDraw.Draw(image), ImageFont.load_default(size=36)


def create_scan_pdf(data_dir: Path) -> Path:
    """Two image-only pages: fixed readable maintenance, month and version facts."""
    import pymupdf
    source = data_dir / 'synthetic-coffee-maintenance.pdf'
    document = pymupdf.open()
    try:
        for number in (1, 2):
            image, draw, font = _canvas()
            draw.rectangle((40, 40, 920, 680), outline='#27504c', width=5)
            lines = ['COFFEE MACHINE MAINTENANCE', 'Synthetic training document',
                     'October 2026', 'Checklist version 2.0', '',
                     '1. Switch off and unplug the machine.',
                     '2. Clean the filter and rinse the water tank.',
                     '3. Descale, then flush with fresh water.' if number == 1 else
                     '3. Check seals and replace worn gaskets.',
                     '4. Record maintenance in the service log.', '', f'Page {number} of 2']
            for index, text in enumerate(lines):
                draw.text((65, 65 + index*51), text, fill='#163936', font=font)
            encoded = io.BytesIO(); image.save(encoded, format='PNG')
            page = document.new_page(width=720, height=540)
            page.insert_image(page.rect, stream=encoded.getvalue())
        with source.open('xb') as handle:
            handle.write(document.tobytes(deflate=True))
    finally:
        document.close()
    return source


def _plant_frame(stage: int, progress: int):
    """Code-native diagrams, visibly different pruning/rooting/transplant stages."""
    image, draw, font = _canvas()
    image.paste((250-progress*2, 248-progress*2, 240-progress*2), (0, 0, 960, 720))
    labels = ('1. PRUNING A STEM CUTTING', '2. ROOTING IN WATER', '3. TRANSPLANTING TO SOIL')
    draw.text((50, 45), 'PLANT PROPAGATION - SYNTHETIC DEMO', fill='#173b2a', font=font)
    draw.text((50, 110), labels[stage], fill='#173b2a', font=font)
    draw.line((450, 490, 450, 230), fill='#236336', width=16)
    draw.ellipse((330, 230, 450, 300), fill='#3c9952')
    draw.ellipse((450, 320, 580, 390), fill='#62af45')
    if stage == 0:
        draw.line((440, 425, 650, 480), fill='#777777', width=15)
        draw.line((440, 425, 650, 380), fill='#aaaaaa', width=15)
        draw.ellipse((625, 455, 715, 535), outline='#cf5935', width=14)
        draw.ellipse((625, 335, 715, 415), outline='#cf5935', width=14)
        draw.line((410, 420, 485, 420), fill='#cf5935', width=7)
        caption = 'Cut a healthy stem below a node.'
    elif stage == 1:
        draw.rectangle((330, 430, 585, 620), fill='#a9dbe3', outline='#417685', width=6)
        draw.line((450, 385, 450, 520), fill='#236336', width=16)
        for delta in (-70, -35, 35, 70):
            draw.line((450, 510, 450+delta, 590), fill='#f7f5dc', width=6)
        caption = 'Place the cutting in water until roots grow.'
    else:
        draw.polygon(((315, 470), (600, 470), (555, 640), (360, 640)), fill='#bb7047')
        draw.ellipse((315, 445, 600, 500), fill='#57422e')
        draw.line((450, 400, 450, 485), fill='#236336', width=16)
        caption = 'Move the rooted cutting into potting soil.'
    draw.text((50, 665), caption, fill='#173b2a', font=font)
    # A bounded moving indicator avoids exact duplicate still frames while the
    # three explanatory scenes remain stable for the production sampler.
    draw.rectangle((50, 180, 60 + progress*30, 195), fill=('#cf5935', '#417685', '#bb7047')[stage])
    return image


def create_video(data_dir: Path) -> Path:
    """Six seconds / 72 frames / three stages; locally encoded MP4 only."""
    import av
    source = data_dir / 'synthetic-plant-propagation.mp4'
    with source.open('xb') as handle:
        with av.open(handle, mode='w', format='mp4') as container:
            stream = container.add_stream('mpeg4', rate=12)
            stream.width, stream.height, stream.pix_fmt = 960, 720, 'yuv420p'
            for index in range(72):
                frame = av.VideoFrame.from_image(_plant_frame(index//24, index % 24))
                for packet in stream.encode(frame): container.mux(packet)
            for packet in stream.encode(): container.mux(packet)
    return source
