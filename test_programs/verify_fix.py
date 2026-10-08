import sqlite3
import pandas as pd

db_path = r'c:\Users\kurok\Downloads\G_ADC\ADC_08\db\my_app_data.db'

def verify_fix():
    conn = sqlite3.connect(db_path)
    try:
        # Get one example
        df = pd.read_sql_query("SELECT auto_id, overtake_by FROM Detection WHERE overtake_by IS NOT NULL LIMIT 1", conn)
        if df.empty:
            print("No overtake data")
            return
            
        row = df.iloc[0]
        my_id = row['auto_id']
        partner_id = row['overtake_by']
        
        print(f"My ID: {my_id}, Partner ID (from overtake_by): {partner_id}")
        
        # Check if partner exists by auto_id
        partner = pd.read_sql_query(f"SELECT auto_id, x1, y1, x2, y2, class_id FROM Detection WHERE auto_id={partner_id}", conn)
        print("Partner lookup by auto_id:")
        print(partner)
        
        if not partner.empty:
            print("CONFIRMED: overtake_by references auto_id")
        else:
            print("FAILED: Partner not found by auto_id")
            
    finally:
        conn.close()

if __name__ == "__main__":
    verify_fix()
