# Third-party libraries

The dashboard bundles the following JavaScript libraries, vendored here so it
works fully offline with no CDN or network fetches. All are MIT-licensed, which
is compatible with this project's AGPL-3.0 license. Each file retains its
original copyright and license header.

| File | Library | Version | License | Upstream |
| --- | --- | --- | --- | --- |
| `3d-force-graph.min.js` | 3D Force-Directed Graph | 1.80.0 | MIT | https://github.com/vasturiano/3d-force-graph |
| `cytoscape.min.js` | Cytoscape.js | 3.30.2 | MIT | https://github.com/cytoscape/cytoscape.js |
| `graphology.umd.min.js` | Graphology | — | MIT | https://github.com/graphology/graphology |
| `graphology-library.min.js` | Graphology standard library (ForceAtlas2, communities-louvain) | — | MIT | https://github.com/graphology/graphology |

To update a library, replace the file with a fresh minified build from its
upstream release and keep this table in sync. No build step is required.
