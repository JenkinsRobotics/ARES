# Bundled third-party libraries

Files under `apps/web/static/vendor/` are redistributed verbatim from their
upstream projects. Minified builds strip their license banners, so the notices
are reproduced here to satisfy the MIT attribution requirement.

Do not edit anything in `vendor/`. To upgrade, replace the directory with a
fresh upstream build and update the version and notice below.

---

## KaTeX 0.16.22 — MIT
Upstream: https://github.com/KaTeX/KaTeX
Files: `vendor/katex/0.16.22/`

```
The MIT License (MIT)

Copyright (c) 2013-2020 Khan Academy and other contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## js-yaml 4.1.0 — MIT
Upstream: https://github.com/nodeca/js-yaml
Files: `vendor/js-yaml/4.1.0/`
(The shipped build retains its own `@license MIT` banner.)

```
(The MIT License)

Copyright (C) 2011-2015 by Vitaly Puzrin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

---

## streaming-markdown — MIT
Upstream: https://github.com/thetarnav/streaming-markdown
Author: Damian Tarnawski
Files: `vendor/smd.min.js`

The upstream repository declares `"license": "MIT"` in `package.json`. The
minified build shipped here carries no banner and the upstream repository
serves no standalone `LICENSE` file at the paths checked, so the MIT grant is
recorded from that declaration rather than reproduced verbatim. If you vendor a
newer build, capture the upstream notice if one has since been added.
