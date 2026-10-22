"""PyInstaller で exe にするときの入口。"""

import sys

from scantext.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
