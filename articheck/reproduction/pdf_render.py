"""Bounded page-image worker. No artifact code, model keys or browser involved."""
import json
from pathlib import Path
import resource
import sys


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (15,15))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (1024**3,1024**3))
    import pypdfium2 as pdfium
    output=Path(sys.argv[2]);selected=json.loads(sys.argv[3])
    if len(selected)>24 or any(type(n) is not int or n<1 for n in selected):
        raise ValueError('Invalid image selection')
    doc=pdfium.PdfDocument(sys.argv[1])
    if not 1<=len(doc)<=150:
        raise ValueError('Unsupported page count')
    manifest=[];total=0
    for number in selected:
        page=doc[number-1]
        width,height=page.get_size()
        if min(width,height)<=0:
            raise ValueError('Invalid page dimensions')
        target_px=1600 if len(selected)<=2 else 1100
        bitmap=page.render(scale=target_px/max(width,height))
        image=bitmap.to_pil().convert('RGB')
        dest=output/f'page-{number}.jpg'
        image.save(dest,format='JPEG',quality=82 if len(selected)<=2 else 74,optimize=False)
        total+=dest.stat().st_size
        if total>12_000_000:
            raise ValueError('Image context exceeds 12 MB')
        manifest.append({'page':number,'file':dest.name,'width':image.width,'height':image.height})
        image.close();bitmap.close();page.close()
    doc.close()
    (output/'images.json').write_text(json.dumps(manifest))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__,file=sys.stderr)
        raise SystemExit(2)
