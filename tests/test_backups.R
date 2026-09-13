# Run from the repository root: Rscript tests/test_backups.R
# Load definitions without sourcing the Windows UI dependencies.
env <- new.env(parent=globalenv())
for (expr in parse('R/make_rosters_from_zero.R')) {
  if (is.call(expr) && identical(expr[[1]], as.name('<-')) &&
      as.character(expr[[2]]) %in% c('initialize_created_players_log','save_memcard')) {
    eval(expr, env)
  }
}
expect_error <- function(code, pattern) {
  msg <- tryCatch({ force(code); NA_character_ }, error=conditionMessage)
  stopifnot(!is.na(msg), grepl(pattern, msg, fixed=TRUE))
}
root <- tempfile('mvp-backup-test-')
dir.create(root)
original_wd <- getwd()
setwd(root)
tryCatch({
  dir.create('data')
  env$initialize_created_players_log('data/created_players.csv', 0)
  log <- read.csv('data/created_players.csv', check.names=FALSE)
  stopifnot(nrow(log)==0, identical(names(log),
    c('bbrefminors_id','Birth Year','Birth Month','Birth Date','created_time')))
  writeLines('existing log', 'existing.csv')
  env$initialize_created_players_log('existing.csv', 1)
  stopifnot(identical(readLines('existing.csv'), 'existing log'))
  expect_error(env$initialize_created_players_log('missing.csv', 1),
               'Missing player log for a resumed run')

  # Exercise real filesystem copies; stub only UI, clock and sleep.
  env$Sys.sleep <- function(...) invisible(NULL)
  env$Sys.time <- function() '2026-09-13 12:00:00'
  env$quick_run_ahk_SendEvent <- function(...) invisible(NULL)
  env$csv_date <- '2026-09-05'
  card <- 'G://My Drive//Games/PCSX2/memcards/MVP05Rosters-20260905.ps2'
  # Map the Windows card input to a local fixture without accessing drive G.
  local_card <- file.path(root, 'card.ps2')
  writeBin(as.raw(0:255), local_card)
  env$file.copy <- function(from, to) {
    from[from == card] <- local_card
    base::file.copy(from, to)
  }
  writeLines('step,org,substep,subsubstep\n1,1,1,0',
             'data/create_rosters_from_zero_progress.csv')
  run_backup <- function() {
    calls <- 0L
    env$is_on_manage_rosters_statistics <- function() {
      calls <<- calls+1L
      calls != 2L
    }
    env$save_memcard()
  }
  run_backup()
  dest <- 'data/progress_backups/2026-09-05/2026-09-13 12-00-00'
  stopifnot(length(list.files(dest))==3,
    identical(readBin(file.path(dest, basename(card)), 'raw', 256), as.raw(0:255)))
  expect_error(run_backup(), 'Unable to create backup directory')
  env$Sys.time <- function() '2026-09-13 12:00:01'
  unlink('data/created_players.csv')
  expect_error(run_backup(), 'Backup failed for: ./data/created_players.csv')
}, finally={setwd(original_wd); unlink(root, recursive=TRUE)})
cat('Backup regression checks passed\n')
