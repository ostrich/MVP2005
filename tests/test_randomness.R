# Run from the repository root: Rscript tests/test_randomness.R
source('R/helpers.R')
draw <- function() list(runif(10), rnorm(10), sample(1:100, 20))
RNGkind('Mersenne-Twister', 'Inversion', 'Rejection')
set.seed(42)
before <- .Random.seed
expected <- with_stable_seed('player', draw())
stopifnot(identical(before, .Random.seed))
RNGkind("L'Ecuyer-CMRG", 'Box-Muller', 'Rejection')
set.seed(99)
before_kind <- RNGkind()
before <- .Random.seed
stopifnot(identical(expected, with_stable_seed('player', draw())),
          identical(before_kind, RNGkind()), identical(before, .Random.seed))
tryCatch(with_stable_seed('player', stop('expected failure')), error=function(e) NULL)
stopifnot(identical(before_kind, RNGkind()), identical(before, .Random.seed))
stopifnot(identical(expected, with_stable_seed('outer', with_stable_seed('player', draw()))))
rm(.Random.seed, envir=.GlobalEnv)
invisible(with_stable_seed('player', draw()))
stopifnot(!exists('.Random.seed', envir=.GlobalEnv, inherits=FALSE),
          identical(before_kind, RNGkind()))

# Test the actual per-player choice expressions without starting the UI.
choices <- function(file, target, row) {
  definitions <- parse(file)
  fn <- Filter(function(x) is.call(x) && identical(x[[1]],as.name('<-')) &&
    is.call(x[[3]]) && identical(x[[3]][[1]],as.name('function')), definitions)[[1]]
  expr <- Filter(function(x) is.call(x) && identical(x[[1]],as.name('<-')) &&
    identical(x[[2]],as.name(target)), as.list(fn[[3]][[3]])[-1])[[1]]
  env <- new.env(); env$df <- row
  eval(expr,env)
}
players <- read.csv('data/MVProsters/MVProsters_2026-09-05.csv',check.names=FALSE)
for (file in c('R/make_player.R','R/morph_player.R')) {
  target <- if (grepl('morph', file)) 'pitch_trajectory' else 'random_values'
  first <- choices(file,target,players[1,])
  invisible(choices(file,target,players[2,]))
  stopifnot(identical(first,choices(file,target,players[1,])))
}
# Old helpers already loaded in an interactive session must not suppress new ones.
for (file in c('R/ootp.R','R/make_player.R','R/morph_player.R')) {
  env <- new.env(parent=baseenv())
  env$round_to_discrete <- env$typeout2 <- function(...) NULL
  env$source <- function(path) sys.source(path,envir=env)
  guards <- Filter(function(x) is.call(x) && identical(x[[1]],as.name('if')),parse(file))
  eval(guards[[1]],env)
  stopifnot(is.function(env$set_stable_seed),is.function(env$with_stable_seed))
}
cat('Randomness regression checks passed\n')
