import os
import subprocess

# Deliberately bad fixture code. Never run this.
subprocess.run(input("cmd> "), shell=True)
eval(input("expr> "))
os.system("rm -rf /tmp/cache")
