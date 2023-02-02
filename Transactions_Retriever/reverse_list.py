import sys, os, json

if (len(sys.argv) >= 2):
    list_filename = sys.argv[1]
    with open(list_filename, 'r') as file:
        raw_list = file.read().replace('\'', '\"').replace('\n', '')
    the_list = json.loads(raw_list)
else:
    exit()

the_list.reverse()
with open(list_filename, 'w') as output_file:
    print(json.dumps(the_list), file=output_file)

