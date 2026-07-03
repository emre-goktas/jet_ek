import fitz, tempfile, os
fd, p = tempfile.mkstemp()
os.write(fd, b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')
os.close(fd)
try:
    doc = fitz.open(p)
    print("Success")
except Exception as e:
    print("Failed:", str(e))
os.remove(p)


"""Error in jet_rename for e7efa98f7b224edd90c43fdd2afccad8: Failed to rename file: Files.upload() got an unexpected keyword argument 'mime_type'
INFO:     127.0.0.1:47516 - "POST /ai/jet-rename/e7efa98f7b224edd90c43fdd2afccad8 HTTP/1.1" 400 Bad Request
Error in jet_rename for 9f9b109bca3a4a6e893b2d535404a88d: Failed to rename file: Files.upload() got an unexpected keyword argument 'mime_type'
INFO:     127.0.0.1:47516 - "POST /ai/jet-rename/9f9b109bca3a4a6e893b2d535404a88d HTTP/1.1" 400 Bad Request
Error in jet_rename for 4e3e13f7095a4be3901271d781f9dec2: Failed to rename file: Files.upload() got an unexpected keyword argument 'mime_type'
INFO:     127.0.0.1:47516 - "POST /ai/jet-rename/4e3e13f7095a4be3901271d781f9dec2 HTTP/1.1" 400 Bad Request"""