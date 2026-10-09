set -eu
work=$(mktemp -d /tmp/zog-systemd-native-XXXXXX)
trap 'rm -rf "$work"' EXIT
cd "$work"
printf test > sample
setfattr -n user.zog -v checked sample
getfattr --only-values -n user.zog sample | grep -x checked
setfacl -m u:21002:r-- sample
getfacl -n sample | grep 'user:21002:r--'
printf 'compression fixture\n' > input
lz4 -f input data.lz4
lz4 -d data.lz4 output
cmp input output
kmod --version
pkg-config --exists libattr libacl libcrypt liblz4 libpcre2-8 libkmod
cat > native.c <<'C'
#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>
#include <lz4.h>
#include <crypt.h>
#include <sys/acl.h>
#include <libkmod.h>
#include <assert.h>
#include <string.h>
int main(void) {
 char packed[128],unpacked[128]; int n=LZ4_compress_default("fixture",packed,8,128);
 assert(n>0 && LZ4_decompress_safe(packed,unpacked,n,128)==8);
 assert(!strcmp(unpacked,"fixture"));
 char *value=crypt("fixture","$6$zogtest$"); assert(value && !strncmp(value,"$6$",3));
 acl_t a=acl_from_text("u::rw-,g::r--,o::---"); assert(a && acl_valid(a)==0);acl_free(a);
 int err; PCRE2_SIZE off; pcre2_code *re=pcre2_compile((PCRE2_SPTR)"^zog[0-9]+$",PCRE2_ZERO_TERMINATED,0,&err,&off,NULL);assert(re);
 pcre2_match_data *md=pcre2_match_data_create_from_pattern(re,NULL);assert(md);
 assert(pcre2_match(re,(PCRE2_SPTR)"zog42",5,0,0,md,NULL)>0);
 pcre2_match_data_free(md);pcre2_code_free(re);
 struct kmod_ctx *ctx=kmod_new(NULL,NULL); assert(ctx);kmod_unref(ctx);
 return 0;
}
C
gcc native.c -o native $(pkg-config --cflags --libs libacl libcrypt liblz4 libpcre2-8 libkmod)
./native
printf '%s\n' ZOG_SYSTEMD_NATIVE_INSTALLED_PASS
