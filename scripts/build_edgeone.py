"""Build an allowlisted upload directory; never copy .env, runs or user materials."""
import argparse
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('__init__.py', 'review_api.py', 'edgeone_review.py',
           'hosted_api.py', 'hosted_auth.py', 'hosted_review.py', 'hosted_store.py', 'hosted_github.py',
           'hosted_sandbox.py', 'hosted_gpu.py', 'hosted_runner.py', 'hosted_uploads.py',
           'hosted_images.py', 'hosted_sources.py', 'hosted_audit.py', 'kg_service.py', 'kg_literature.py', 'kg_methods.py', 'reproduction/pdf_render.py',
           'reproduction/paper_text.py', 'reproduction/pdf_extract.py', 'reproduction/protocol.py')


def build(output, *, esbuild=None):
    output = Path(output).resolve()
    # Only overwrite this builder's designated, ignored staging directory.
    expected = ROOT / '.edgeone-build'
    if output != expected:
        raise ValueError('Build output must be the repository .edgeone-build directory')
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(ROOT / 'web/dist', output)
    # Some EdgeOne POPs serve .mjs as application/octet-stream. Use ordinary .js
    # URLs in the upload only; source modules and their Node test imports stay intact.
    modules = list(output.rglob('*.mjs'))
    for path in modules:
        if path.with_suffix('.js').exists():
            raise ValueError('Module filename collision: ' + path.name)
    for path in output.rglob('*'):
        if path.is_file() and path.suffix in {'.js', '.mjs', '.html', '.css'}:
            text = path.read_text()
            if '.mjs' in text:
                path.write_text(text.replace('.mjs', '.js'))
    for path in modules:
        path.rename(path.with_suffix('.js'))
    if esbuild:
        entrypoint = output / 'app.js'
        bundled = output / 'workbench.bundle.js'
        subprocess.run([esbuild, str(entrypoint), '--bundle', '--platform=browser', '--format=esm',
                        '--external:./vendor/pdfjs/*', f'--outfile={bundled}'], check=True)
        bundled.replace(entrypoint)
    digest = hashlib.sha256()
    for path in sorted(output.rglob('*.js')):
        digest.update(path.relative_to(output).as_posix().encode())
        digest.update(path.read_bytes())
    entry = 'app.' + digest.hexdigest()[:12] + '.js'
    (output / 'app.js').rename(output / entry)
    index = output / 'index.html'
    index.write_text(index.read_text().replace('src="./app.js"', 'src="./' + entry + '"'))
    template = ROOT / 'deploy/edgeone'
    shutil.copytree(template / 'cloud-functions', output / 'cloud-functions')
    shutil.copy2(template / 'edgeone.json', output / 'edgeone.json')
    shutil.copy2(template / 'package.json', output / 'package.json')
    package = output / 'cloud-functions/articheck'
    for name in MODULES:
        dest = package / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'articheck' / name, dest)
    (package / 'reproduction/__init__.py').write_text('')
    # The cloud adapter uses the same origin, no API credentials in this file.
    (output / 'deployment.json').write_text(json.dumps({'review_api_mode': 'synchronous','login_required':True}))
    # Explicit archive root avoids hidden staging-folder filtering by upload tools.
    with zipfile.ZipFile(output.with_suffix('.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(output).as_posix())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / '.edgeone-build'))
    parser.add_argument('--esbuild', help='Bundle the workbench entry with this esbuild executable')
    args = parser.parse_args()
    print(build(args.output, esbuild=args.esbuild))
