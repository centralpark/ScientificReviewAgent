https://api.semanticscholar.org/graph/v1/paper/10.1158/1538-7445.fusionpositive26-a027?fields=title,abstract,url,publicationDate,publicationTypes,journal

gcloud storage cat gs://aacr-abstracts-data-lake/*.csv | wc -l

84.6 MB for 76544 records

--command="python" \
  --args="process_aacr_dois.py","--batch-size","500","--save-frequency","1000","--failed-dois-json","gs://aacr-abstracts-data-lake/failed_dois_1773156557.json" \


"--csv-file=gs://aacr-abstracts-data-lake/combined_aacr_results.csv",
                "--batch-size=500",
                "--failed-dois-json=gs://aacr-abstracts-data-lake/failed_dois_1773156557.json",
                "--csv_file_path=dois.csv"


https://api.crossref.org/works/doi/10.1158/0008-can-64-24-corc


gsutil mv \
gs://aacr-abstracts-data-lake/aacr_publication/paper_details_batches_1773197197_35.jsonl \
gs://aacr-abstracts-data-lake/aacr_publication/paper_details_batches_1773197197_35.json

kaggle_1773232775560


https://api.crossref.org/members/1086/works?filter=from-pub-date%3A2004-01-01%2Cuntil-pub-date%3A2004-12-31&cursor=%2A&rows=100&select=DOI%2Ctitle%2Ctype%2Cabstract%2CURL%2Cpublished%2Ccontainer-title%2Cissue%2Cpage&mailto=siheng.he%40rinuagene.com