ai_runtime_add_to_env() {
    local env_var=$1
    local new_path=$2

    local env_paths=$(eval echo \$$env_var)

    if [[ ! $env_paths == *"$new_path"* ]]; then
        export $env_var=$env_paths:$new_path
    fi
}

# take args if given
if [ $# -eq 2 ]; then
    AIX_USER_NAME=$1
    AIX_USER_HOME_DIR=$2
else
    AIX_USER_NAME=`whoami`
    AIX_USER_HOME_DIR=$HOME
fi

source ${AIX_USER_HOME_DIR}/anaconda3/etc/profile.d/conda.sh
conda activate ${AIX_USER_NAME}_ai_runtime_env
ai_runtime_add_to_env LD_LIBRARY_PATH /usr/lib/x86_64-linux-gnu/
ai_runtime_add_to_env LD_LIBRARY_PATH $CONDA_PREFIX/lib/

unset AIX_USER_HOME_DIR
unset AIX_USER_NAME
unset ai_runtime_add_to_env
