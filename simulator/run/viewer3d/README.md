# 3D tab of the twin viewer

`scene3d.js` is the source; `hp3d.bundle.js` is what `run/demo.py` inlines in `demo/hydropin_viewer.html`
(three.js 0.170 + OrbitControls bundled, so the page works offline).

Rebuild after editing the source:

    npm install three@0.170.0 esbuild
    npx esbuild scene3d.js --bundle --minify --format=iife --global-name=HP3D --outfile=hp3d.bundle.js
