#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#if !defined(__aarch64__)
#error This diagnostic requires native AArch64 code generation.
#endif

int main(int argc, char **argv)
{
    char *end = NULL;
    long expected;
    int value = 0;
    if (argc != 2 || sizeof(void *) != 8) {
        return 64;
    }
    errno = 0;
    expected = strtol(argv[1], &end, 10);
    if (errno != 0 || end == argv[1] || *end != '\0') {
        return 65;
    }
    for (int i = 1; i <= 6; ++i) {
        value += 2 * i;
    }
    printf("SDK_RESULT=%d\nPTR_BITS=%zu\n", value, 8 * sizeof(void *));
    return value == expected ? 0 : 9;
}
