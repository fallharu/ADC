import pandas as pd

csv_path = 'overtake_analysis_dump.csv'
output_txt = 'direction_analysis.txt'

try:
    df = pd.read_csv(csv_path)
    with open(output_txt, 'w', encoding='utf-8') as f:
        f.write("--- Travel Direction Distribution ---\n")
        f.write(str(df['Travel_Direction'].value_counts(dropna=False)))
        f.write("\n\n--- Sample Rows with Direction ---\n")
        f.write(str(df[['Event_ID', 'Travel_Direction', 'Video_Name']].head(10)))
        
    print("Analysis saved to direction_analysis.txt")
except Exception as e:
    print(f"Error: {e}")
