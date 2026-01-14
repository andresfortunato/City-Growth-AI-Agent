pkg <- c("tidyverse", "data.table", "purrr")

for (i in pkg) {
  if (!requireNamespace(i, quietly = TRUE)) {
    install.packages(i)
    library(i, character.only = TRUE)
  } else {
    library(i, character.only = TRUE)
  }
}

# ---- helper: read only MSA CSVs from a CEW "annual_by_area" ZIP ----
read_msa_from_zip <- function(zip_url) {
  tf_zip <- tempfile(fileext = ".zip")
  download.file(zip_url, tf_zip, mode = "wb", quiet = TRUE)
  
  z <- unzip(tf_zip, list = TRUE)
  
  msa_names <- z$Name %>%
    { .[grepl("\\.csv$", ., ignore.case = TRUE) & grepl("MSA", basename(.))] }
  
  if (!length(msa_names)) return(data.table())
  
  exdir <- tempfile()
  dir.create(exdir)
  unzip(tf_zip, files = msa_names, exdir = exdir)
  
  paths <- file.path(exdir, msa_names)
  
  cols_keep <- c(
    "area_fips","area_title","year","qtr","size_code","size_title",
    "annual_avg_estabs_count","annual_avg_emplvl","total_annual_wages",
    "avg_annual_pay","annual_avg_wkly_wage","agglvl_title"
  )
  
  read_keep <- function(p) {
    fread(p, showProgress = FALSE, colClasses = list(character = "area_fips")) %>%
      { .[, intersect(cols_keep, names(.)), with = FALSE] } %>%
      { .[agglvl_title == "MSA, Total Covered"] }
  }
  
  lapply(paths, read_keep) %>%
    rbindlist(use.names = TRUE, fill = TRUE)
}

# ---- function that retrieves MSA data for specified years ----
get_msa_data <- function(years, drop_pr = TRUE) {
  cat("Downloading data for years:", paste(years, collapse = ", "), "\n")
  
  urls <- years %>%
    sprintf("https://data.bls.gov/cew/data/files/%d/csv/%d_annual_by_area.zip", ., .)
  
  msa <- urls %>%
    map(read_msa_from_zip) %>%
    bind_rows() %>%
    select(area_fips, area_title, year, qtr, size_code, size_title,
           annual_avg_estabs_count, annual_avg_emplvl, total_annual_wages,
           avg_annual_pay, annual_avg_wkly_wage) %>%
    mutate(year = as.integer(year))
  
  area_names <- msa %>%
    distinct(area_fips, area_title)
  
  out <- msa %>%
    select(-area_title) %>%
    left_join(area_names, by = "area_fips")
  
  if (drop_pr) {
    out <- out %>% 
      filter(!grepl("\\bPR\\b", area_title)) %>% 
      mutate(area_title = str_remove_all(area_title, " MSA")) %>% 
      mutate(state = substr(area_title, nchar(area_title)-1, nchar(area_title)))
  }
  
  cat("Data retrieval complete. Total rows:", nrow(out), "\n")
  out
}

# ---- Main execution ----

# Specify the years you want to download
years <- 2024  # Testing with one year

# Get the data
msa_data <- get_msa_data(years)

# Preview the data
cat("\nData structure:\n")
str(msa_data)

cat("\nFirst few rows:\n")
print(head(msa_data))

# Save to CSV
output_file <- "msa_wages_employment_data.csv"
write.csv(msa_data, output_file, row.names = FALSE)
cat("\nData saved to:", output_file, "\n")

# Optional: Save to RDS format (more efficient for R)
output_rds <- "msa_wages_employment_data.rds"
saveRDS(msa_data, output_rds)
cat("Data also saved to:", output_rds, "\n")

# Summary statistics
cat("\n=== Summary Statistics ===\n")
cat("Number of unique MSAs:", n_distinct(msa_data$area_fips), "\n")
cat("Years covered:", paste(sort(unique(msa_data$year)), collapse = ", "), "\n")
cat("Total observations:", nrow(msa_data), "\n")

