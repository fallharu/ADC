import os
import sys

def tail(filename, n=50):
    try:
        with open(filename, 'rb') as f:
            f.seek(0, 2)
            filesize = f.tell()
            block_size = 1024
            lines = []
            
            # Read back from end
            pos = filesize
            while pos > 0 and len(lines) < n:
                read_size = min(block_size, pos)
                pos -= read_size
                f.seek(pos)
                block = f.read(read_size)
                
                # Split lines and handle potential partial lines at boundaries
                # (Simple approach: just decode and split)
                try:
                    text = block.decode('utf-16le', errors='ignore') # Try utf-16le first as viewed earlier
                except:
                   text = block.decode('utf-8', errors='ignore')

                new_lines = text.splitlines()
                if lines:
                    new_lines[-1] += lines[0] # Merge boundary
                    lines = new_lines[:-1] + lines 
                else:
                    lines = new_lines
            
            return lines[-n:]
    except Exception as e:
        return [f"Error reading file: {e}"]

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fname = sys.argv[1]
        for line in tail(fname):
            print(line)
