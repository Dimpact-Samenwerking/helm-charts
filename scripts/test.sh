OPENFORMS_IMAGE_TAG_LATEST=2.7.9

curl -s https://raw.githubusercontent.com/open-formulieren/open-forms/refs/heads/master/CHANGELOG.rst | awk "/^${OPENFORMS_IMAGE_TAG_LATEST}/ {flag=1} /^[0-9]+\\.[0-9]+\\.[0-9]+/  && !/^${OPENFORMS_IMAGE_TAG_LATEST}/ {flag=0} flag"