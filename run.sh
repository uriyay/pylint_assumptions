PYTHONPATH=$PYTHONPATH:$PWD pylint --load-plugins=pylint_assumptions --disable=all --enable=assumptions-checker $1
