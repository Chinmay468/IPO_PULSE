import olefile

fn = "/tmp/holding_test.xlsx"
ole = olefile.OleFileIO(fn)
print("OLE streams:", ole.listdir())

for stream_path in ole.listdir():
    stream_name = "/".join(stream_path)
    stream_data = ole.openstream(stream_path).read()
    print(f"\nStream '{stream_name}' (len {len(stream_data)}):")
    print(repr(stream_data[:300]))
    try:
        print("Decoded snippet:", stream_data[:300].decode("utf-8", errors="replace"))
    except Exception as e:
        print(e)
