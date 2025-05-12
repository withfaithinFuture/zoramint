input_file = "ACCTIVEPR.txt"  # Имя входного файла
output_file = "readyPR.txt"  # Имя выходного файла

with open(input_file, "r") as infile, open(output_file, "w") as outfile:
    for line in infile:
        line = line.strip()  # Убираем лишние пробелы и переносы строк
        parts = line.split(":")
        if len(parts) == 4:
            ip, port, user, password = parts
            new_format = f"http://{user}:{password}@{ip}:{port}\n"
            outfile.write(new_format)

print("Файл успешно обработан и сохранён в output.txt")