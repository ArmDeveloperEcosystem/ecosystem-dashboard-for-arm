/* Userspace xl configuration parsing only; no domain or device operations. */
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libxlutil.h>

static int expect_result(int actual, int expected, const char *operation)
{
    if (actual == expected)
        return 0;
    fprintf(stderr, "%s: expected result %d, got %d\n",
            operation, expected, actual);
    return 1;
}

static int expect_string(XLU_Config *cfg, const char *key, const char *expected)
{
    const char *actual = NULL;

    if (expect_result(xlu_cfg_get_string(cfg, key, &actual, 0), 0, key))
        return 1;
    if (actual == NULL || strcmp(actual, expected) != 0) {
        fprintf(stderr, "%s: parsed string differs from input\n", key);
        return 1;
    }
    return 0;
}

static int expect_long(XLU_Config *cfg, const char *key, long expected)
{
    long actual = -1;

    if (expect_result(xlu_cfg_get_long(cfg, key, &actual, 0), 0, key))
        return 1;
    if (actual != expected) {
        fprintf(stderr, "%s: expected %ld, got %ld\n", key, expected, actual);
        return 1;
    }
    return 0;
}

static int check_positive(const char *name, long memory, long vcpus)
{
    char kernel[128], disk[256], input[2048];
    const char *item;
    XLU_ConfigList *list = NULL;
    XLU_Config *cfg;
    int length, entries = -1, result = 1;

    /* The caller's validated name fits all three buffers without escaping. */
    snprintf(kernel, sizeof(kernel), "/boot/Image-%s", name);
    snprintf(disk, sizeof(disk),
             "format=raw,vdev=xvda,access=rw,target=/tmp/%s.img", name);
    length = snprintf(input, sizeof(input),
                      "# Arm guest configuration fixture; never booted\n"
                      "name = '%s'\n"
                      "memory = %ld\n"
                      "vcpus = %ld\n"
                      "kernel = '%s'\n"
                      "disk = [ '%s' ]\n"
                      "vif = [ 'bridge=xenbr0', 'bridge=xenbr1' ]\n",
                      name, memory, vcpus, kernel, disk);
    if (length < 0 || (size_t)length >= sizeof(input)) {
        fputs("configuration fixture is too long\n", stderr);
        return 1;
    }
    cfg = xlu_cfg_init(stderr, "valid-arm-guest.cfg");
    if (cfg == NULL) {
        fputs("could not allocate parser configuration\n", stderr);
        return 1;
    }
    if (expect_result(xlu_cfg_readdata(cfg, input, length), 0, "valid syntax") ||
        expect_string(cfg, "name", name) ||
        expect_long(cfg, "memory", memory) ||
        expect_long(cfg, "vcpus", vcpus) ||
        expect_string(cfg, "kernel", kernel))
        goto out;

    if (expect_result(xlu_cfg_get_list(cfg, "disk", &list, &entries, 0),
                      0, "disk list"))
        goto out;
    if (list == NULL || entries != 1) {
        fputs("disk: expected exactly one list entry\n", stderr);
        goto out;
    }
    item = xlu_cfg_get_listitem(list, 0);
    if (item == NULL || strcmp(item, disk) != 0 ||
        xlu_cfg_get_listitem(list, 1) != NULL) {
        fputs("disk: parsed list contents or bounds are incorrect\n", stderr);
        goto out;
    }
    if (expect_result(xlu_cfg_get_list(cfg, "vif", &list, &entries, 0),
                      0, "vif list"))
        goto out;
    if (list == NULL || entries != 2) {
        fputs("vif: expected exactly two list entries\n", stderr);
        goto out;
    }
    item = xlu_cfg_get_listitem(list, 0);
    if (item == NULL || strcmp(item, "bridge=xenbr0") != 0) {
        fputs("vif: incorrect first list entry\n", stderr);
        goto out;
    }
    item = xlu_cfg_get_listitem(list, 1);
    if (item == NULL || strcmp(item, "bridge=xenbr1") != 0 ||
        xlu_cfg_get_listitem(list, 2) != NULL) {
        fputs("vif: incorrect second list entry or bounds\n", stderr);
        goto out;
    }
    printf("PASS valid-arm-guest: name=%s memory=%ld vcpus=%ld kernel=%s\n",
           name, memory, vcpus, kernel);
    result = 0;
out:
    xlu_cfg_destroy(cfg);
    return result;
}

enum negative_case { BAD_SYNTAX, BAD_NUMBER, BAD_TYPE, MISSING_FIELD };

static int check_negative(enum negative_case which, const char *label,
                          const char *input)
{
    XLU_Config *cfg = xlu_cfg_init(stderr, label);
    long number = -1;
    const char *string = NULL;
    int result = 1, rc;

    if (cfg == NULL) {
        fputs("could not allocate negative parser configuration\n", stderr);
        return 1;
    }
    rc = xlu_cfg_readdata(cfg, input, (int)strlen(input));
    if (which == BAD_SYNTAX) {
        /* Getters must not be used after a parse failure. */
        result = expect_result(rc, EINVAL, label);
    } else if (!expect_result(rc, 0, label)) {
        if (which == MISSING_FIELD)
            result = expect_result(
                xlu_cfg_get_string(cfg, "kernel", &string, 0), ESRCH, label);
        else
            result = expect_result(
                xlu_cfg_get_long(cfg, "memory", &number, 0), EINVAL, label);
    }
    xlu_cfg_destroy(cfg);
    if (result == 0)
        printf("PASS %s\n", label);
    return result;
}

static int parse_positive_number(const char *text, long *number)
{
    char *end;

    if (text[0] < '0' || text[0] > '9')
        return 1;
    errno = 0;
    *number = strtol(text, &end, 10);
    return errno != 0 || *end != '\0' || *number < 1 || *number > INT_MAX;
}

int main(int argc, char **argv)
{
    const char *name = "arm-smoke";
    long memory = 384, vcpus = 2;

    if (argc != 1 && argc != 4) {
        fprintf(stderr, "Usage: %s [NAME MEMORY_MIB VCPUS]\n", argv[0]);
        return 2;
    }
    if (argc == 4) {
        name = argv[1];
        if (parse_positive_number(argv[2], &memory) ||
            parse_positive_number(argv[3], &vcpus)) {
            fputs("MEMORY_MIB and VCPUS must be positive integers <= INT_MAX\n",
                  stderr);
            return 2;
        }
    }
    if (name[0] == '\0' || strlen(name) > 63 ||
        strspn(name, "abcdefghijklmnopqrstuvwxyz"
                     "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") != strlen(name)) {
        fputs("NAME must contain 1-63 ASCII letters, digits, underscores, dots or hyphens\n",
              stderr);
        return 2;
    }
    if (check_positive(name, memory, vcpus) ||
        check_negative(BAD_SYNTAX, "reject-malformed-syntax",
                       "name = 'bad'\ndisk = [ 'unfinished'\n") ||
        check_negative(BAD_NUMBER, "reject-nonnumeric-memory",
                       "memory = 'not-a-number'\n") ||
        check_negative(BAD_TYPE, "reject-list-as-number",
                       "memory = [ '256', '512' ]\n") ||
        check_negative(MISSING_FIELD, "detect-missing-kernel",
                       "name = 'missing-kernel'\nmemory = 256\nvcpus = 1\n"))
        return 1;

    puts("xen-toolstack-smoke-ok");
    return 0;
}
