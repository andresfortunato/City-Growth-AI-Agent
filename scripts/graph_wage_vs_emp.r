pkg <- c("tidyverse", "data.table", "stringr", "purrr", "lubridate", "scales", "ggrepel")

for (i in pkg) {
  if (!requireNamespace(i, quietly = TRUE)) {
    install.packages(i)
    library(i, character.only = TRUE)
  } else {
    library(i, character.only = TRUE)
  }
}

standard_theme <- theme(
  legend.position = "bottom",
  plot.title = element_text(hjust = .5, size = 16, color = "black"),
  plot.subtitle = element_text(hjust = .5),
  legend.text = element_text(size = 14, color = "black"),
  legend.background = element_blank(),
  legend.box.background = element_blank(),
  legend.key = element_blank(),
  legend.title = element_text(size = 14, colour = "black"),
  axis.title = element_text(size = 16, colour = "black"),
  axis.text = element_text(size = 14, color = "black"),
  strip.text = element_text(size = 16, color = "black"),
  axis.line = element_line(size = .4, colour = "black"),
  axis.ticks = element_line(size = .4, colour = "black"),
  plot.margin = margin(.3, .3, .3, .3, "cm"),
  panel.background = element_blank(),
  strip.background = element_blank(),
  panel.grid.major = element_line(size = .4, colour = "lightgrey", linetype = "longdash")
)


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

# ---- function that takes years, reads, merges, and computes CAGRs ----
get_msa_cagr <- function(years, drop_pr = TRUE) {
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
  out
}


# Change the years here and everything else updates automatically
years <- c(2022, 2024)
total_msa <- get_msa_cagr(years)

# ---- combine and compute 4-year CAGRs (2020 -> 2024) ----
total_msa_change <- total_msa %>% 
  arrange(area_fips, year) %>%
  group_by(area_fips) %>%
  mutate(
    cagr_avg_pay      = (avg_annual_pay            / lag(avg_annual_pay))^(1/4) - 1,
    cagr_estab        = (annual_avg_estabs_count   / lag(annual_avg_estabs_count))^(1/4) - 1,
    cagr_avg_weekwage = (annual_avg_wkly_wage      / lag(annual_avg_wkly_wage))^(1/4) - 1,
    cagr_emp          = (annual_avg_emplvl         / lag(annual_avg_emplvl))^(1/4) - 1
  ) %>%
  ungroup()

se <- c("SC", "NC", "GA", "TN", "VA", "AL")

graph <- total_msa_change %>% 
  na.omit() %>% 
  filter(cagr_emp > -0.1) %>% 
  mutate(southeast = ifelse(state %in% se, "Southeast", "Other"))

x0 <- mean(graph$cagr_emp)
y0 <- mean(graph$cagr_avg_pay)

# x_se <- mean(graph$cagr_emp[graph$southeast == "Southeast"])
# y_se <- mean(graph$cagr_avg_pay[graph$southeast == "Southeast"])

# # png("wage vs emp growth sav 22-24.png", width = 23, height = 15, res = 300, units = "cm")
# graph %>% 
#   ggplot() +
#   geom_point(aes(cagr_emp, cagr_avg_pay, color = southeast)) +
#   geom_text_repel(data = subset(graph, state %in% se),
#                   aes(cagr_emp, cagr_avg_pay, label = area_title)) +
#   geom_point(data = subset(graph, area_title == "Savannah, GA"),
#              aes(cagr_emp, cagr_avg_pay), size = 2, color = "darkred") +
#   geom_text_repel(data = subset(graph, area_title == "Savannah, GA"),
#                   aes(cagr_emp, cagr_avg_pay, label = area_title), fontface = "bold", color = "darkred") +
#   geom_vline(xintercept = x0, color = "darkgrey") +
#   geom_hline(yintercept = y0, color = "darkgrey") +
#   # southeast averages (different color so it stands out)
#   geom_vline(xintercept = x_se, color = "orange", linetype = "dashed") +
#   geom_hline(yintercept = y_se, color = "orange", linetype = "dashed") +
#   geom_abline(slope =  1, intercept = y0 - x0, linetype = "longdash", color = "darkgrey") +
#   geom_abline(slope = -1, intercept = y0 + x0, linetype = "longdash", color = "darkgrey") +
#   scale_color_manual(values = c("darkgrey", "orange")) +
#   standard_theme +
#   scale_y_continuous(labels = percent) +
#   scale_x_continuous(labels = percent) +
#   labs(x = "Employment Growth (CAGR), 2022-2024",
#        y = "Average Annual Pay Growth (CAGR), 2022-2024", color = "")
# dev.off()




graph %>% 
  ggplot() +
  geom_point(aes(cagr_emp, cagr_avg_pay, color = southeast)) +
  geom_text_repel(data = subset(graph, state %in% se),
                  aes(cagr_emp, cagr_avg_pay, label = area_title)) +
  geom_point(data = subset(graph, area_title == "Savannah, GA"),
             aes(cagr_emp, cagr_avg_pay), size = 2, color = "darkred") +
  geom_text_repel(data = subset(graph, area_title == "Savannah, GA"),
                  aes(cagr_emp, cagr_avg_pay, label = area_title), fontface = "bold", color = "darkred") +
  geom_vline(xintercept = x0, color = "darkgrey") +
  geom_hline(yintercept = y0, color = "darkgrey") +
  # southeast averages (different color so it stands out)
  geom_abline(slope =  1, intercept = y0 - x0, linetype = "longdash", color = "darkgrey") +
  geom_abline(slope = -1, intercept = y0 + x0, linetype = "longdash", color = "darkgrey") +
  
  # --- annotations ---
  annotate("text", x = max(graph$cagr_emp), y = y0, 
           label = "Average", color = "darkgrey", vjust = -0.5) +
  annotate("text", x = max(graph$cagr_emp)*0.9, 
           y = (y0 - x0) + (max(graph$cagr_emp)*0.9), 
           label = "Slope = 1", color = "darkgrey", 
           angle = 45, vjust = -0.5) +
  
  scale_color_manual(values = c("darkgrey", "orange")) +
  standard_theme +
  scale_y_continuous(labels = scales::percent) +
  scale_x_continuous(labels = scales::percent) +
  labs(x = "Employment Growth (CAGR), 2022-2024",
       y = "Average Annual Pay Growth (CAGR), 2022-2024", color = "")

# 
# graph %>% 
#   ggplot() +
#   geom_point(aes(cagr_emp, cagr_estab, color = southeast)) +
#   geom_smooth(aes(cagr_emp, cagr_estab, color = southeast), se = F) +
#   geom_text_repel(data = subset(graph, state %in% se),
#                   aes(cagr_emp, cagr_estab, label = area_title)) +
#   geom_point(data = subset(graph, area_title == "Savannah, GA"),
#              aes(cagr_emp, cagr_estab), size = 2, color = "darkred") +
#   geom_text_repel(data = subset(graph, area_title == "Savannah, GA"),
#                   aes(cagr_emp, cagr_estab, label = area_title), fontface = "bold", color = "darkred") +
#   scale_color_manual(values = c("darkgrey", "orange")) +
#   standard_theme +
#   scale_y_continuous(labels = percent) +
#   scale_x_continuous(labels = percent) +
#   labs(x = "Employment Growth (CAGR), 2020-2024",
#        y = "Establishment Growth (CAGR), 2020-2024", color = "")
# 
