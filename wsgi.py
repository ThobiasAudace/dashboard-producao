import sys
import os

path = '/home/ThobiasAndrade01/dashboard_diretoria'
if path not in sys.path:
    sys.path.insert(0, path)

os.chdir(path)

from app import app as application
