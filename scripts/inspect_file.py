import os
import io

def inspect():
    fn = "/tmp/holding_test.xlsx"
    if not os.path.exists(fn):
        fn = "Your Holding Details - C58634663.xlsx"
    
    with open(fn, "rb") as f:
        data = f.read()

    print("File size:", len(data))
    print("First 32 bytes:", list(data[:32]))
    print("First 64 chars repr:", repr(data[:64]))

    # 1. xlrd
    try:
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
        print("\n--- XLRD SUCCESS ---")
        for r in range(sheet.nrows):
            print(f"Row {r}: {[sheet.cell_value(r, c) for c in range(sheet.ncols)]}")
    except Exception as e:
        print("XLRD error:", e)

    # 2. openpyxl
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data))
        sheet = wb.active
        print("\n--- OPENPYXL SUCCESS ---")
        for r in sheet.iter_rows(values_only=True):
            print(r)
    except Exception as e:
        print("Openpyxl error:", e)

    # 3. pandas
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(data))
        print("\n--- PANDAS SUCCESS ---")
        print(df)
    except Exception as e:
        print("Pandas error:", e)

if __name__ == "__main__":
    inspect()
