import re

from helper import maps, version

with open('README.md') as fp:
    old_README = fp.read()  # noqa: N816

output = old_README

output = re.sub(
    '<div id="map_parameter">.*?<\\/div>',
    '<div id="map_parameter">\n\n' + '\n'.join(map(lambda x: f'- `{x}`', maps.keys())) + '\n</div>',
    output,
    1,
    re.DOTALL,
)

output = re.sub(
    '<span id="version">.*?<\\/span>',
    f'<span id="version">{version}</span>',
    output,
    1,
    re.DOTALL,
)

if output == old_README:
    print('README identical after update')
else:
    with open('README.md', 'w') as fp:
        fp.write(output)
