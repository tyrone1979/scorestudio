os.chdir(installdir)
if installdir not in sys.path:
    sys.path.insert(0, installdir)
